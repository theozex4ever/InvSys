"""Copied-data upgrade, backup restore and rollback rehearsal on disposable inventories.

The public bridge is exercised against real temporary SQLite databases built from the
committed pre-migration fixture. The native rehearsal itself (``scripts/upgrade_rehearsal.py``
driving the frozen bundle) runs in the package CI job; these cover the decisions that
need no display: what the fixture holds, that opening and using it loses nothing, which
backup belongs to which inventory, how the documented restore behaves and fails, and
that the rehearsal flags every kind of loss.
"""

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from inventory_control import utilities
from inventory_control.backup import backup_database
from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore
from inventory_control.utilities import UtilityContext

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package_bundle = load_script("package_bundle")
rehearsal = load_script("upgrade_rehearsal")

# Changing the fixture is a deliberate, reviewed act: update these with it.
FIXTURE_COUNTS = {
    "locations": 4,
    "parts": 8,
    "lots": 8,
    "inventory_balances": 11,
    "inventory_transactions": 28,
    "shipments": 4,
    "shipment_components": 7,
    "bom_components": 6,
    "settings": 3,
}
FIXTURE_DIGEST = "8bfb5a770ae68928af1673d1be059fe14ce87563f6253551d1ed21390cb390bb"
FIXTURE_SHA256 = "ea6da4ea945c05f5ad56535386a04dce1a17cc3d44b16e7c33fefa3fb4d67861"
BOM_SHIPMENT = "SHP-20260905-0001"
MULTI_LOT_BOM_SHIPMENT = "SHP-20260908-0001"


@pytest.fixture
def inventory(tmp_path: Path) -> Path:
    database = tmp_path / "operations" / "inventory.db"
    rehearsal.install_fixture(database)
    return database


def open_bridge(database: Path) -> tuple[InventoryStore, InventoryBridge]:
    store = InventoryStore(database, seed=False)
    return store, InventoryBridge(store, UtilityContext.for_launch(database))


def sqlite_files(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


# ------------------------------------------------------------------- fixture


def test_the_pre_migration_fixture_is_the_reviewed_one(inventory):
    state = rehearsal.snapshot(inventory)
    assert rehearsal.counts(state) == FIXTURE_COUNTS
    assert rehearsal.digest(state) == FIXTURE_DIGEST
    assert rehearsal.fixture_sha256() == FIXTURE_SHA256
    assert state["integrity_check"] == "ok"
    assert state["foreign_key_violations"] == 0


def test_the_fixture_ledger_reconciles_with_its_balances_and_shipments(inventory):
    assert rehearsal.reconcile(rehearsal.snapshot(inventory)) == []


def test_the_fixture_covers_every_record_kind_the_upgrade_must_keep(inventory):
    state = rehearsal.snapshot(inventory)
    types = {row[2] for row in state["tables"]["inventory_transactions"]["rows"].values()}
    assert {
        "RECEIVE",
        "SHIP",
        "SHIP_BOM",
        "BOM_CONSUME",
        "MOVE_OUT",
        "MOVE_IN",
        "COUNT_CORRECTION",
    } <= types
    trace = rehearsal.component_trace(state)
    assert sorted(trace) == [BOM_SHIPMENT, MULTI_LOT_BOM_SHIPMENT]
    # The second BOM shipment consumed one component from two Lots.
    assert [lot for part, lot, _, _ in trace[MULTI_LOT_BOM_SHIPMENT] if part == "UPG-BOLT"] == [
        "B-100",
        "B-200",
    ]
    settings = {row[0]: row[1] for row in state["tables"]["settings"]["rows"].values()}
    assert settings == {
        "schema_version": "1",
        "last_operator": "J. Okafor",
        "desktop_theme": "dark",
    }


def test_the_fixture_schema_is_exactly_what_the_application_creates_today(inventory):
    """The migration adds no schema change: a fresh database has the fixture's schema."""
    fresh = inventory.parent / "fresh.db"
    InventoryStore(fresh, seed=False).engine.dispose()
    assert rehearsal.snapshot(fresh)["schema"] == rehearsal.snapshot(inventory)["schema"]


def test_installing_the_fixture_never_overwrites_an_existing_file(inventory):
    with pytest.raises(rehearsal.RehearsalError, match="Refusing to overwrite"):
        rehearsal.install_fixture(inventory)


def test_a_file_that_is_not_the_fixture_is_not_installed(tmp_path):
    other = tmp_path / "other.sql"
    other.write_text("CREATE TABLE t (id INTEGER);\n", encoding="utf-8")
    with pytest.raises(rehearsal.RehearsalError, match="not a pre-migration fixture"):
        rehearsal.install_fixture(tmp_path / "x.db", other)
    assert not (tmp_path / "x.db").exists()


# ------------------------------------------------------- upgrade through the bridge


def test_opening_the_copied_inventory_changes_nothing_and_reads_everything(inventory):
    before = rehearsal.snapshot(inventory)
    store, bridge = open_bridge(inventory)
    try:
        assert bridge.preferences()["data"] == {"operator": "J. Okafor", "theme": "dark"}
        part = bridge.part_detail("UPG-BOLT")["data"]
        assert part["quantity"] == 36
        assert {
            (item["location"], item["lot_number"]): item["quantity"] for item in part["balances"]
        } == {("Stock", "B-100"): 0, ("Stock", "B-200"): 34, ("Scrap", "B-200"): 2}
        assert bridge.part_detail("UPG-RETIRED")["data"]["active"] is False
        low = {item["part_number"] for item in bridge.dashboard()["data"]["low_stock"]}
        assert "UPG-LOW" in low
        page = bridge.history({"query": "UPG-WIDGET"})["data"]
        assert page["total"] >= 5
    finally:
        store.engine.dispose()
    assert rehearsal.compare(before, rehearsal.snapshot(inventory), identical=True) == []


def test_bom_shipment_snapshots_survive_later_bom_edits_and_restart(inventory):
    shipped = {}
    for number in (BOM_SHIPMENT, MULTI_LOT_BOM_SHIPMENT):
        store, bridge = open_bridge(inventory)
        try:
            shipped[number] = bridge.shipment_detail(number)["data"]
        finally:
            store.engine.dispose()
    # The BOM edited after these shipments (bolt 4 -> 5 each, plus a gasket) is not what
    # the shipments consumed: History reads the persisted per-Lot snapshots.
    assert {
        c["lot_number"]: c["quantity"]
        for c in shipped[MULTI_LOT_BOM_SHIPMENT]["consumed_components"]
        if c["part_number"] == "UPG-BOLT"
    } == {"B-100": 36, "B-200": 4}
    store, bridge = open_bridge(inventory)
    try:
        assert bridge.bom_definition("UPG-FRAME")["data"]["components"][0]["quantity_per"] == 5
        assert bridge.save_bom_component(
            {"parent": "UPG-FRAME", "component": "UPG-PLATE", "quantity_per": 9}
        )["ok"]
    finally:
        store.engine.dispose()
    store, bridge = open_bridge(inventory)
    try:
        for number, detail in shipped.items():
            assert bridge.shipment_detail(number)["data"] == detail
    finally:
        store.engine.dispose()


def test_new_work_on_the_copy_keeps_every_existing_record_and_the_ledger_reconciles(inventory):
    before = rehearsal.snapshot(inventory)
    store, bridge = open_bridge(inventory)
    try:
        store.receive("UPG-WIDGET", 12, "Stock", "W-3", "Desktop smoke", "PO-NEW")
        store.move("UPG-WIDGET", 5, "Stock", "Shipping Bench", "W-3", "Desktop smoke")
        store.adjust("UPG-WIDGET", "Stock", "W-3", 6, "Desktop smoke", "Recount")
        plan = store.prepare_bom_shipment("UPG-SUB", 2, "Stock")
        store.ship("UPG-SUB", 2, "Stock", "Epsilon", "Desktop smoke", expected_bom_plan=plan)
        bridge.save_operator("Desktop smoke")
    finally:
        store.engine.dispose()
    after = rehearsal.snapshot(inventory)
    assert rehearsal.compare(before, after, identical=False, stock_moved=True) == []
    assert any("inventory_balances" in p for p in rehearsal.compare(before, after, identical=False))
    assert rehearsal.reconcile(after) == []
    assert (
        rehearsal.counts(after)["inventory_transactions"] > FIXTURE_COUNTS["inventory_transactions"]
    )
    # Not identical: the work is there. The one setting that moved is a preference.
    assert rehearsal.compare(before, after, identical=True)


# ------------------------------------------------------------- backups per inventory


def test_startup_and_manual_backups_refer_to_the_selected_inventory(inventory, tmp_path):
    other = tmp_path / "another" / "inventory.db"
    other.parent.mkdir()
    store = InventoryStore(other, seed=False)  # a different, unrelated inventory
    store.engine.dispose()
    other_before = rehearsal.snapshot(other)
    selected = rehearsal.snapshot(inventory)
    context = UtilityContext.for_launch(inventory)

    startup = backup_database(inventory, context.backups, reason="startup")
    assert startup is not None
    assert startup.parent == inventory.parent / "backups"
    assert rehearsal.compare(selected, rehearsal.snapshot(startup), identical=True) == []

    store, bridge = open_bridge(inventory)
    try:
        manual = Path(bridge.create_backup()["data"]["created"]["path"])
    finally:
        store.engine.dispose()
    assert manual.parent == inventory.parent / "backups"
    assert rehearsal.compare(selected, rehearsal.snapshot(manual), identical=True) == []
    assert not (other.parent / "backups").exists()
    assert rehearsal.snapshot(other) == other_before


def test_source_defaults_and_an_explicit_database_keep_their_own_folders(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setattr(utilities, "DB_PATH", home / "data" / "inventory.db")
    monkeypatch.setattr(utilities, "BACKUP_DIR", home / "backups")
    monkeypatch.setattr(utilities, "EXPORT_DIR", home / "exports")
    monkeypatch.setattr(utilities, "LOG_DIR", home / "logs")
    rehearsal.install_fixture(home / "data" / "inventory.db")
    explicit = tmp_path / "chosen" / "inventory.db"
    rehearsal.install_fixture(explicit)

    default = UtilityContext.for_launch(None)
    chosen = UtilityContext.for_launch(explicit)
    assert default.database == home / "data" / "inventory.db"
    assert default.backups == home / "backups"
    assert chosen.database == explicit.resolve()
    assert chosen.backups == explicit.parent.resolve() / "backups"
    default_backup = backup_database(default.database, default.backups, reason="startup")
    chosen_backup = backup_database(chosen.database, chosen.backups, reason="startup")
    assert default_backup is not None
    assert chosen_backup is not None
    assert default_backup.parent == home / "backups"
    assert chosen_backup.parent == explicit.parent.resolve() / "backups"
    assert sqlite_files(home / "backups") == [default_backup.name]
    assert sqlite_files(explicit.parent / "backups") == [chosen_backup.name]


# ------------------------------------------------------------------------ restore


def make_later_inventory(inventory: Path) -> tuple[Path, dict[str, Any]]:
    """Back up the pre-upgrade state, then add ledger activity; return backup and state."""
    context = UtilityContext.for_launch(inventory)
    backup = backup_database(inventory, context.backups, reason="startup")
    assert backup is not None
    store, _ = open_bridge(inventory)
    try:
        store.receive("UPG-WIDGET", 7, "Stock", "W-9", "Late operator")
        store.ship("UPG-WIDGET", 3, "Stock", "Late customer", "Late operator", lot_number="W-9")
    finally:
        store.engine.dispose()
    return backup, rehearsal.snapshot(inventory)


def test_closed_app_restore_returns_the_backup_and_keeps_later_work_aside(inventory):
    original = rehearsal.snapshot(inventory)
    backup, later = make_later_inventory(inventory)
    aside_root = inventory.parent / "restore-aside"
    # An application killed mid-write leaves sidecars: they belong to the replaced file.
    inventory.with_name("inventory.db-wal").write_bytes(b"stale")
    inventory.with_name("inventory.db-shm").write_bytes(b"stale")

    result = rehearsal.restore_from_backup(inventory, backup, aside_root, stamp="20261024-120000")

    kept = aside_root / "restore-aside-20261024-120000"
    assert result["aside_directory"] == str(kept)
    assert sorted(path.name for path in kept.iterdir()) == [
        "inventory.db",
        "inventory.db-shm",
        "inventory.db-wal",
    ]
    assert not inventory.with_name("inventory.db-wal").exists()
    assert not inventory.with_name("inventory.db-shm").exists()
    assert not inventory.with_name("inventory.db.restoring").exists()
    assert rehearsal.compare(original, rehearsal.snapshot(inventory), identical=True) == []
    assert rehearsal.compare(later, rehearsal.snapshot(kept / "inventory.db"), identical=True) == []
    assert backup.is_file()

    dropped = rehearsal.dropped_entries(rehearsal.snapshot(inventory), later)
    assert dropped["ledger_entries"] == 2
    assert dropped["by_type"] == {"RECEIVE": 1, "SHIP": 1}
    assert len(dropped["shipments"]) == 1

    store, bridge = open_bridge(inventory)
    try:
        widget = bridge.part_detail("UPG-WIDGET")["data"]
        assert widget["quantity"] == 88
        assert all(item["lot_number"] != "W-9" for item in widget["balances"])
    finally:
        store.engine.dispose()


def test_restoring_never_deletes_the_database_it_replaces(inventory):
    backup, later = make_later_inventory(inventory)
    rehearsal.restore_from_backup(inventory, backup, inventory.parent / "restore-aside")
    asides = list((inventory.parent / "restore-aside").glob("restore-aside-*/inventory.db"))
    assert len(asides) == 1
    assert rehearsal.digest(rehearsal.snapshot(asides[0])) == rehearsal.digest(later)


def test_every_restore_refusal_and_file_failure_leaves_the_database_untouched(tmp_path):
    probes = rehearsal.restore_failure_probes(tmp_path)
    by_name = {probe["name"]: probe for probe in probes}
    applicable = [probe for probe in probes if probe["applicable"]]
    assert len(applicable) >= 7
    assert [probe["name"] for probe in applicable if not probe["passed"]] == []
    assert "does not exist" in by_name["backup-does-not-exist"]["message"]
    assert "put back" in by_name["copy-fails-after-database-moved-aside"]["message"]
    assert by_name["database-folder-is-read-only"]["applicable"] == (
        os.name == "posix" and os.geteuid() != 0
    )
    assert by_name["database-held-open-by-another-program"]["applicable"] == (
        sys.platform == "win32"
    )


def test_a_failure_while_putting_the_database_back_names_where_it_is(inventory, monkeypatch):
    backup, _ = make_later_inventory(inventory)
    original_replace = Path.replace

    def failing_replace(self, target):
        # Moving aside works; putting back (into the database folder) is refused.
        if Path(target).name == "inventory.db" and Path(target).parent == inventory.parent:
            raise PermissionError(13, "Permission denied")
        return original_replace(self, target)

    def fail() -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", failing_replace)
    with pytest.raises(rehearsal.RestoreRefused, match="could NOT be put back; it is in"):
        rehearsal.restore_from_backup(
            inventory, backup, inventory.parent / "restore-aside", after_aside=fail
        )
    assert any((inventory.parent / "restore-aside").glob("*/inventory.db"))


# ------------------------------------------------------------ comparison helpers


def tamper(database: Path, statement: str) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(statement)


@pytest.mark.parametrize(
    "statement,expected",
    [
        (
            "DELETE FROM inventory_transactions WHERE id = 5",
            "inventory_transactions row 5 is missing",
        ),
        (
            "UPDATE shipment_components SET quantity = 99 WHERE id = 1",
            "shipment_components row 1 changed (quantity)",
        ),
        (
            "UPDATE inventory_balances SET quantity = 77 WHERE id = 5",
            "inventory_balances row 5 changed",
        ),
        (
            "UPDATE settings SET value = '2' WHERE key = 'schema_version'",
            "settings row schema_version changed",
        ),
        (
            "DELETE FROM settings WHERE key = 'desktop_theme'",
            "settings row desktop_theme is missing",
        ),
        ("ALTER TABLE parts ADD COLUMN extra TEXT", "The schema changed"),
        (
            "UPDATE shipments SET recipient = 'Someone else' WHERE id = 3",
            "shipments row 3 changed (recipient)",
        ),
    ],
)
def test_a_lost_or_rewritten_record_is_reported(inventory, statement, expected):
    before = rehearsal.snapshot(inventory)
    tamper(inventory, statement)
    assert any(
        expected in problem
        for problem in rehearsal.compare(before, rehearsal.snapshot(inventory), identical=False)
    )


def test_preferences_may_change_but_nothing_else_in_settings(inventory):
    before = rehearsal.snapshot(inventory)
    tamper(inventory, "UPDATE settings SET value = 'Desktop smoke' WHERE key = 'last_operator'")
    after = rehearsal.snapshot(inventory)
    assert rehearsal.compare(before, after, identical=False) == []
    assert rehearsal.compare(before, after, identical=True)


def test_reconcile_reports_balances_and_snapshots_that_disagree_with_the_ledger(inventory):
    tamper(inventory, "UPDATE inventory_balances SET quantity = quantity + 1 WHERE id = 5")
    tamper(inventory, "UPDATE shipment_components SET quantity = quantity + 1 WHERE id = 1")
    tamper(inventory, "UPDATE shipments SET quantity = quantity + 1 WHERE id = 1")
    problems = rehearsal.reconcile(rehearsal.snapshot(inventory))
    assert any("Balance part/lot/location" in problem for problem in problems)
    assert any("component snapshot differs" in problem for problem in problems)
    assert any("SHP-20260904-0001 shipped 30, not 31" in problem for problem in problems)


def test_snapshots_read_a_wal_database_without_changing_it(inventory):
    store = InventoryStore(inventory, seed=False)  # WAL mode, connection still open
    try:
        store.receive("UPG-WIDGET", 1, "Stock", "W-WAL", "Operator")
        names = sqlite_files(inventory.parent)
        state = rehearsal.snapshot(inventory)
        assert sqlite_files(inventory.parent) == names
        assert any(row[2] == "W-WAL" for row in state["tables"]["lots"]["rows"].values())
    finally:
        store.engine.dispose()


# -------------------------------------------------------- the whole rehearsal flow


class StandInApplication(rehearsal.Launcher):
    """Stands for the desktop application: backs up, opens the store, works, backs up."""

    def __init__(self, misbehaviour: str = "") -> None:
        super().__init__(None, False)
        self.misbehaviour = misbehaviour
        self.launches = 0

    def describe(self) -> dict[str, Any]:
        return {"kind": "stand-in"}

    def run(self, database: Path, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
        self.launches += 1
        context = UtilityContext.for_launch(database)
        if self.misbehaviour != "no-startup-backup":
            backup_database(database, context.backups, reason="startup")
        store = InventoryStore(database, seed=False)
        bridge = InventoryBridge(store, context)
        try:
            store.receive("UPG-WIDGET", 2, "Stock", f"NEW-{self.launches}", "Desktop smoke")
            store.set_setting("last_operator", "Desktop smoke")
            if self.misbehaviour != "no-manual-backup":
                bridge.create_backup()
        finally:
            store.engine.dispose()
        match self.misbehaviour:
            case "loses-a-ledger-row":
                tamper(database, "DELETE FROM inventory_transactions WHERE id = 3")
            case "alters-the-schema" if self.launches == 1:
                tamper(database, "ALTER TABLE lots ADD COLUMN surprise TEXT")
            case "rewrites-a-snapshot":
                tamper(database, "UPDATE shipment_components SET quantity = 1 WHERE id = 2")
            case "writes-to-the-default-location":
                Path(env["INVSYS_HOME"]).mkdir(parents=True, exist_ok=True)
        return {
            "arguments": [],
            "exit_code": 7 if self.misbehaviour == "crashes" else 0,
            "seconds": 0.1,
            "stdout": "Desktop smoke passed; no HTTP server.",
            "stderr": "",
        }


@pytest.fixture
def display(monkeypatch):
    monkeypatch.setattr(package_bundle, "require_display", lambda: None)


def run_rehearsal(
    tmp_path: Path, misbehaviour: str = ""
) -> tuple[bool, dict[str, Any], StandInApplication]:
    app = StandInApplication(misbehaviour)
    evidence = tmp_path / "evidence" / "upgrade.json"
    passed = rehearsal.rehearse(app, tmp_path / "work", evidence)
    return passed, json.loads(evidence.read_text(encoding="utf-8")), app


def test_the_rehearsal_upgrades_restarts_restores_and_reopens(tmp_path, display):
    passed, record, app = run_rehearsal(tmp_path)

    assert passed
    assert record["result"] == "passed"
    assert app.launches == 3
    assert [step["name"] for step in record["steps"]] == [
        "fixture-is-intact-before-upgrade",
        "upgrade-open-and-workflows",
        "restart-and-workflows",
        "closed-app-restore-of-the-pre-upgrade-backup",
        "reopen-after-restore-and-workflows",
        "nothing-written-outside-the-selected-inventory",
        "restore-refusals-and-file-failures-leave-the-database-untouched",
    ]
    assert all(step["passed"] for step in record["steps"])
    assert record["fixture"]["snapshot_digest"] == FIXTURE_DIGEST
    assert record["fixture"]["counts"] == FIXTURE_COUNTS
    assert record["fixture"]["preferences"] == {
        "last_operator": "J. Okafor",
        "desktop_theme": "dark",
    }
    assert sorted(record["fixture"]["component_snapshots"]) == [
        BOM_SHIPMENT,
        MULTI_LOT_BOM_SHIPMENT,
    ]
    restore = next(s for s in record["steps"] if s["name"].startswith("closed-app-restore"))
    assert restore["reconciliation_required"]["ledger_entries"] > 0
    assert restore["reconciliation_required"]["by_type"] == {"RECEIVE": 2}
    assert not (tmp_path / "work" / "unexpected-home").exists()
    # The disposable copy was rolled back to the pre-upgrade inventory.
    final = rehearsal.snapshot(tmp_path / "work" / "inventory" / "inventory.db")
    assert any(row[2] == "NEW-3" for row in final["tables"]["lots"]["rows"].values())
    assert not any(row[2] == "NEW-1" for row in final["tables"]["lots"]["rows"].values())


@pytest.mark.parametrize(
    "misbehaviour,expected",
    [
        ("loses-a-ledger-row", "inventory_transactions row 3 is missing"),
        ("alters-the-schema", "The schema changed"),
        ("rewrites-a-snapshot", "shipment_components row 2 changed"),
        ("no-startup-backup", "Expected one new startup backup"),
        ("no-manual-backup", "created no manual backup"),
        ("crashes", "The launch failed (exit 7)"),
        ("writes-to-the-default-location", "was created"),
    ],
)
def test_the_rehearsal_fails_when_the_application_loses_or_misplaces_anything(
    tmp_path, display, misbehaviour, expected
):
    passed, record, _ = run_rehearsal(tmp_path, misbehaviour)

    assert not passed
    assert record["result"] == "failed"
    problems = [problem for step in record["steps"] for problem in step["problems"]]
    assert any(expected in problem for problem in problems), problems


def test_the_rehearsal_refuses_a_workdir_that_is_not_empty(tmp_path, display):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "inventory.db").write_text("operational?", encoding="utf-8")
    with pytest.raises(rehearsal.RehearsalError, match="must be empty"):
        rehearsal.rehearse(StandInApplication(), workdir, tmp_path / "e.json")
    assert (workdir / "inventory.db").read_text(encoding="utf-8") == "operational?"


# ----------------------------------------------------------------- launchers and CLI


def test_a_source_launch_runs_the_repository_launcher_against_the_selected_copy(
    monkeypatch, tmp_path
):
    seen: dict[str, Any] = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = rehearsal.Launcher(None, False).run(tmp_path / "i.db", tmp_path, {"A": "b"})

    assert seen["command"][0] == sys.executable
    assert seen["command"][1].endswith("inventory_desktop.py")
    assert seen["command"][2:] == ["--database", str(tmp_path / "i.db"), "--smoke-check"]
    assert seen["env"] == {"A": "b"}
    assert result["exit_code"] == 0


def test_a_bundle_launch_uses_the_shared_bundle_runner(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        package_bundle, "run_bundle", lambda *args: calls.append(args) or {"exit_code": 0}
    )
    rehearsal.Launcher(tmp_path / "bundle", True).run(tmp_path / "i.db", tmp_path, {})
    assert calls == [
        (
            tmp_path / "bundle",
            ["--database", str(tmp_path / "i.db"), "--smoke-check"],
            tmp_path,
            {},
            True,
        )
    ]


def test_source_rehearsals_cannot_ask_for_network_isolation(capsys, tmp_path):
    code = rehearsal.main(
        [
            "rehearse",
            "--source",
            "--isolate-network",
            "--workdir",
            str(tmp_path / "w"),
            "--evidence",
            str(tmp_path / "e"),
        ]
    )
    assert code == 1
    assert "--bundle rehearsals only" in capsys.readouterr().err


def test_a_rehearsal_needs_a_target(tmp_path):
    with pytest.raises(SystemExit):
        rehearsal.main(["rehearse", "--workdir", str(tmp_path), "--evidence", str(tmp_path / "e")])


def test_the_committed_fixture_text_is_what_the_generator_writes(tmp_path, monkeypatch):
    """Regeneration is reproducible apart from the provenance line naming the commit."""
    regenerated = tmp_path / "fixture.sql"
    rehearsal.write_fixture(regenerated)
    committed = rehearsal.FIXTURE.read_text(encoding="utf-8").splitlines()
    assert regenerated.read_text(encoding="utf-8").splitlines()[2:] == committed[2:]
    assert committed[0] == rehearsal.FIXTURE_HEADER
    assert committed[1].startswith("-- Written by the application at commit ")
