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
last_known_good = load_script("last_known_good")
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
FIXTURE_SHA256 = "6bdb9faaa8d5daef8cb2872207e113a98b252b790d39dbf99417545273eb7c5c"
BOM_SHIPMENT = "SHP-20260905-0001"
MULTI_LOT_BOM_SHIPMENT = "SHP-20260908-0001"


@pytest.fixture
def inventory(tmp_path: Path) -> Path:
    database = tmp_path / "operations" / "inventory.db"
    rehearsal.install_fixture(database)
    return database


def release_database(workdir: Path) -> Path:
    return workdir / "last-known-good" / "data" / "inventory.db"


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
    assert app.launches == 4
    assert [step["name"] for step in record["steps"]] == [
        "fixture-is-intact-before-upgrade",
        "upgrade-open-and-workflows",
        "restart-and-workflows",
        "closed-app-restore-of-the-pre-upgrade-backup",
        "reopen-after-restore-and-workflows",
        "rollback-to-the-last-known-good-release-on-the-upgraded-inventory",
        "roll-forward-after-rollback-and-workflows",
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
    # The restore returned the pre-upgrade inventory; the launches after it are all that is new.
    final = rehearsal.snapshot(release_database(tmp_path / "work"))
    assert any(row[2] == "NEW-4" for row in final["tables"]["lots"]["rows"].values())
    assert not any(row[2] in ("NEW-1", "NEW-2") for row in final["tables"]["lots"]["rows"].values())


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


def test_a_failed_step_prints_even_when_the_console_cannot_encode_its_text(monkeypatch):
    """A Windows cp1252 console must not turn a failed launch into a traceback."""
    import io

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", console)
    with pytest.raises(SystemExit):
        rehearsal.main(["rehearse"])  # argparse's usage error goes to the same console
    rehearsal.step({"steps": []}, "launch", ["smoke said \ufffd"])

    assert "smoke said ?" in raw.getvalue().decode("cp1252")
    console.detach()


def test_a_rehearsal_needs_a_target(tmp_path):
    with pytest.raises(SystemExit):
        rehearsal.main(["rehearse", "--workdir", str(tmp_path), "--evidence", str(tmp_path / "e")])


def test_the_committed_fixture_text_is_what_the_generator_writes(tmp_path, monkeypatch):
    """The pinned older release, not the current store, writes exactly the committed text."""
    regenerated = tmp_path / "fixture.sql"
    rehearsal.write_fixture(regenerated)
    committed = rehearsal.FIXTURE.read_text(encoding="utf-8").splitlines()
    assert regenerated.read_text(encoding="utf-8").splitlines() == committed
    assert committed[0] == rehearsal.FIXTURE_HEADER
    assert committed[1].endswith(f"at commit {last_known_good.COMMIT}.")


# ------------------------------------------------- the last known-good release (rollback)


def test_the_pinned_release_is_the_original_application_before_the_desktop_frontend(tmp_path):
    info = last_known_good.extract(tmp_path / "release")

    assert info["commit"] == last_known_good.COMMIT
    assert info["tree"] == last_known_good.tree_hash()
    release = tmp_path / "release"
    assert (release / "inventory_visualizer.py").is_file()
    assert (release / "inventory_control" / "ui" / "main_window.py").is_file()
    # The release predates the desktop frontend, its bridge and its packaging.
    assert not (release / "inventory_desktop.py").exists()
    assert not (release / "inventory_control" / "desktop.py").exists()
    assert not list(release.rglob("__pycache__"))
    # Its inventory is not here until an operator's data (or the fixture) is put there.
    assert not (release / "data").exists()
    assert info["files"] == sum(1 for path in release.rglob("*") if path.is_file())


def test_an_unreadable_history_is_reported_with_how_to_fix_it(tmp_path, monkeypatch):
    monkeypatch.setattr(last_known_good, "ROOT", tmp_path)
    with pytest.raises(rehearsal.RehearsalError, match="full history"):
        rehearsal.extract_release(tmp_path / "release")


def test_the_pinned_release_writes_the_same_schema_the_application_creates_today(tmp_path):
    """The older release and today's store agree on every table, column and index."""
    release = tmp_path / "release"
    last_known_good.extract(release)
    old = tmp_path / "old.db"
    rehearsal.build_fixture_database(old, release)
    new = tmp_path / "new.db"
    InventoryStore(new, seed=False).engine.dispose()

    assert rehearsal.snapshot(old)["schema"] == rehearsal.snapshot(new)["schema"]


def test_the_older_release_opens_the_inventory_and_keeps_its_own_backups(tmp_path):
    workdir = tmp_path / "work"
    tree = workdir / "last-known-good"
    last_known_good.extract(tree)
    database = last_known_good.release_database(tree)
    rehearsal.install_fixture(database)
    before = rehearsal.snapshot(database)

    run = last_known_good.run_release("rollback-probe", tree)
    report = json.loads(run.stdout.splitlines()[-1])
    after = rehearsal.snapshot(database)

    assert run.returncode == 0, run.stderr
    assert report["exit_code"] == 0
    assert report["windows_shown"] == 1
    assert Path(report["release"]).resolve() == tree.resolve()
    # What the release itself reads: every record and each BOM shipment's per-Lot snapshot.
    assert report["read_before_work"] == {
        "parts": 8,
        "transactions": 28,
        "shipments": 4,
        "component_snapshots": rehearsal.component_trace(before),
    }
    # Its startup backup is the inventory as it was, kept in the release's own folder.
    backups = sorted(last_known_good.release_backups(tree).glob("inventory-*.db"))
    startup = next(path for path in backups if path.name.endswith("-startup.db"))
    assert rehearsal.compare(before, rehearsal.snapshot(startup), identical=True) == []
    assert [path.name for path in backups if "-manual" in path.name] == [report["manual_backup"]]
    assert not (database.parent / "backups").exists()
    assert rehearsal.compare(before, after, identical=False, stock_moved=True) == []
    assert rehearsal.reconcile(after) == []
    assert report["bom_shipment"] in rehearsal.component_trace(after)


def run_with_release_fault(tmp_path: Path, monkeypatch, fault: str) -> list[str]:
    """Rehearse with a last known-good release that misbehaves after its real run."""
    real = last_known_good.run_release

    def faulty(command: str, tree: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        if command != "rollback-probe":
            return real(command, tree, *arguments)
        result = real(command, tree, *arguments)
        database = last_known_good.release_database(tree)
        match fault:
            case "crashes":
                return subprocess.CompletedProcess(result.args, 3, "", "boom")
            case "no-report":
                return subprocess.CompletedProcess(result.args, 0, "not json\n", "")
            case "loses-a-ledger-row":
                tamper(database, "DELETE FROM inventory_transactions WHERE id = 3")
            case "rewrites-a-snapshot":
                tamper(database, "UPDATE shipment_components SET quantity = 1 WHERE id = 2")
            case "alters-the-schema":
                tamper(database, "ALTER TABLE lots ADD COLUMN surprise TEXT")
            case "reads-less-than-the-inventory":
                report = json.loads(result.stdout.splitlines()[-1])
                report["read_before_work"]["transactions"] -= 1
                return subprocess.CompletedProcess(result.args, 0, json.dumps(report), "")
            case "runs-other-code":
                report = json.loads(result.stdout.splitlines()[-1])
                report["release"] = str(tree.parent)
                return subprocess.CompletedProcess(result.args, 0, json.dumps(report), "")
        return result

    monkeypatch.setattr(last_known_good, "run_release", faulty)
    passed, record, _ = run_rehearsal(tmp_path)
    assert not passed
    assert record["result"] == "failed"
    step = next(s for s in record["steps"] if s["name"].startswith("rollback-to-the-last"))
    assert not step["passed"]
    return step["problems"]


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("crashes", "The release failed (exit 3)"),
        ("no-report", "The release failed"),
        ("loses-a-ledger-row", "inventory_transactions row 3 is missing"),
        ("rewrites-a-snapshot", "shipment_components row 2 changed"),
        ("alters-the-schema", "The schema changed"),
        ("reads-less-than-the-inventory", "The release read transactions"),
        ("runs-other-code", "The release ran code from"),
    ],
)
def test_the_rollback_fails_when_the_older_release_loses_or_misreads_anything(
    tmp_path, display, monkeypatch, fault, expected
):
    problems = run_with_release_fault(tmp_path, monkeypatch, fault)
    assert any(expected in problem for problem in problems), problems


def test_the_rehearsal_records_the_release_it_rolled_back_to(tmp_path, display):
    _, record, _ = run_rehearsal(tmp_path)

    assert record["last_known_good"]["commit"] == last_known_good.COMMIT
    assert record["last_known_good"]["tree"] == last_known_good.tree_hash()
    assert record["last_known_good"]["inventory"] == "data/inventory.db"
    rollback = next(s for s in record["steps"] if s["name"].startswith("rollback-to-the-last"))
    assert rollback["release"]["windows_shown"] == 1
    assert rollback["release"]["read_before_work"]["shipments"] == 4
    assert rollback["release_backup_folder"] == "backups"
    assert len(rollback["startup_backups"]) == 1
    assert len(rollback["manual_backups"]) == 1
    # The roll-forward launch reads the inventory the older release wrote to.
    forward = next(s for s in record["steps"] if s["name"].startswith("roll-forward"))
    assert forward["passed"]
    assert rollback["inventory_counts"]["shipments"] == 6  # the release shipped two more
    assert (
        forward["inventory_counts"]["inventory_transactions"]
        > rollback["inventory_counts"]["inventory_transactions"]
    )


# ------------------------------------------------------- restore cleanup and rollback


def test_a_staging_cleanup_failure_still_puts_the_database_back(inventory, monkeypatch):
    backup, _ = make_later_inventory(inventory)
    before = rehearsal.snapshot(inventory)
    original_unlink = Path.unlink
    checks = []

    def failing_check(path):
        checks.append(path)
        if len(checks) > 1:  # the copy beside the database fails its own check
            raise rehearsal.RestoreRefused("The copy is damaged. Nothing was changed.")

    def failing_unlink(self, *args, **kwargs):
        if self.name.endswith(".restoring"):
            raise PermissionError(13, "Permission denied")
        return original_unlink(self, *args, **kwargs)

    real_check = rehearsal.check_backup
    monkeypatch.setattr(
        rehearsal,
        "check_backup",
        lambda path: (
            real_check(path) if len(checks) < 1 and not checks.append(path) else failing_check(path)
        ),
    )
    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(rehearsal.RestoreRefused) as refused:
        rehearsal.restore_from_backup(inventory, backup, inventory.parent / "restore-aside")
    monkeypatch.undo()

    message = str(refused.value)
    assert "The copy is damaged" in message
    assert "could not be removed" in message
    assert ".restoring" in message
    assert "previous database was put back" in message
    assert rehearsal.compare(before, rehearsal.snapshot(inventory), identical=True) == []


def test_every_recovery_path_is_named_when_nothing_can_be_cleaned_or_put_back(
    inventory, monkeypatch
):
    backup, _ = make_later_inventory(inventory)
    original_replace = Path.replace
    original_unlink = Path.unlink

    def refuse_into_database_folder(self, target):
        if Path(target).parent == inventory.parent:
            raise PermissionError(13, "Permission denied")
        return original_replace(self, target)

    def refuse_staging(self, *args, **kwargs):
        if self.name.endswith(".restoring"):
            raise PermissionError(13, "Permission denied")
        return original_unlink(self, *args, **kwargs)

    def fail() -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", refuse_into_database_folder)
    monkeypatch.setattr(Path, "unlink", refuse_staging)
    with pytest.raises(rehearsal.RestoreRefused) as refused:
        rehearsal.restore_from_backup(
            inventory, backup, inventory.parent / "restore-aside", after_aside=fail
        )
    monkeypatch.undo()
    message = str(refused.value)
    assert "No space left on device" in message
    assert "could NOT be put back" in message
    assert "restore-aside" in message


# ------------------------------------------------------------ evidence destination


@pytest.mark.parametrize("kind", ["database", "text", "symlink", "dangling", "inside-workdir"])
def test_an_existing_evidence_destination_is_refused_before_anything_runs(tmp_path, display, kind):
    workdir = tmp_path / "work"
    destination = tmp_path / "somewhere" / "evidence.json"
    destination.parent.mkdir()
    if kind == "database":
        with closing(sqlite3.connect(destination)) as connection:
            connection.execute("CREATE TABLE precious (id INTEGER)")
        original = destination.read_bytes()
    elif kind == "text":
        destination.write_text("keep me", encoding="utf-8")
        original = destination.read_bytes()
    elif kind == "symlink":
        target = tmp_path / "target.db"
        target.write_bytes(b"SQLite format 3\x00 precious")
        original = target.read_bytes()
        destination.symlink_to(target)
    elif kind == "dangling":
        destination.symlink_to(tmp_path / "nowhere")
        original = b""
    else:
        destination = workdir / "inventory" / "evidence.json"
        original = b""
    app = StandInApplication()

    with pytest.raises(rehearsal.RehearsalError, match="evidence"):
        rehearsal.rehearse(app, workdir, destination)

    assert app.launches == 0
    assert not workdir.exists() or not any(workdir.iterdir())
    if kind in ("database", "text"):
        assert destination.read_bytes() == original
    if kind == "symlink":
        assert (tmp_path / "target.db").read_bytes() == original


def test_the_cli_reports_a_refused_evidence_destination(tmp_path, display, capsys):
    destination = tmp_path / "evidence.json"
    destination.write_text("keep me", encoding="utf-8")
    code = rehearsal.main(
        ["rehearse", "--source", "--workdir", str(tmp_path / "w"), "--evidence", str(destination)]
    )
    assert code == 1
    assert "evidence" in capsys.readouterr().err
    assert destination.read_text(encoding="utf-8") == "keep me"


def test_evidence_is_created_exclusively_even_if_the_file_appears_during_the_run(tmp_path, display):
    destination = tmp_path / "evidence.json"

    class Racing(StandInApplication):
        def run(self, database, cwd, env):
            destination.write_text("someone else's file", encoding="utf-8")
            return super().run(database, cwd, env)

    with pytest.raises(rehearsal.RehearsalError, match="evidence"):
        rehearsal.rehearse(Racing(), tmp_path / "work", destination)
    assert destination.read_text(encoding="utf-8") == "someone else's file"


# --------------------------------------------------------- backup verification (original app)


def test_a_good_backup_verifies_with_its_counts(inventory):
    backup = backup_database(inventory, inventory.parent / "backups", reason="manual")
    report = rehearsal.verify_backup_file(backup)
    assert report["problems"] == []
    assert report["counts"] == FIXTURE_COUNTS
    assert report["integrity_check"] == "ok"


def test_a_backup_that_only_looks_like_a_copy_is_rejected(inventory, tmp_path):
    good = backup_database(inventory, inventory.parent / "backups", reason="manual")
    truncated = tmp_path / "inventory-truncated.db"
    truncated.write_bytes(good.read_bytes()[: good.stat().st_size // 2 + 7])
    garbage = tmp_path / "inventory-garbage.db"
    garbage.write_text("not an SQLite database", encoding="utf-8")
    inconsistent = tmp_path / "inventory-inconsistent.db"
    inconsistent.write_bytes(good.read_bytes())
    tamper(inconsistent, "UPDATE inventory_balances SET quantity = quantity + 1 WHERE id = 5")
    for bad, expected in (
        (truncated, "not a usable SQLite inventory"),
        (garbage, "not a usable SQLite inventory"),
        (inconsistent, "Balance part/lot/location"),
        (tmp_path / "absent.db", "does not exist"),
    ):
        report = rehearsal.verify_backup_file(bad)
        assert any(expected in problem for problem in report["problems"]), (bad, report)


def test_verifying_a_backup_never_changes_it_or_leaves_files_beside_it(inventory):
    backup = backup_database(inventory, inventory.parent / "backups", reason="manual")
    before = (backup.read_bytes(), sqlite_files(backup.parent))
    rehearsal.verify_backup_file(backup)
    assert (backup.read_bytes(), sqlite_files(backup.parent)) == before


def test_the_cli_verifies_a_backup_and_fails_on_a_bad_one(inventory, tmp_path, capsys):
    good = backup_database(inventory, inventory.parent / "backups", reason="manual")
    assert rehearsal.main(["verify-backup", str(good)]) == 0
    assert "28 ledger rows" in capsys.readouterr().out
    bad = tmp_path / "inventory-bad.db"
    bad.write_text("nope", encoding="utf-8")
    assert rehearsal.main(["verify-backup", str(bad)]) == 1


# ------------------------------------------------- reconciliation: identity, minute, WAL


class FrozenMinute:
    """Pins the store's wall clock (minute resolution) while a block runs."""

    def __init__(self, stamp):
        from datetime import datetime

        self.moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M")  # stored times are naive local
        moment = self.moment

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: ARG003  # mirrors datetime.now
                return cls(moment.year, moment.month, moment.day, moment.hour, moment.minute, 45)

        self.cls = Frozen

    def __enter__(self):
        from unittest import mock

        self.patch = mock.patch("inventory_control.store.datetime", self.cls)
        self.patch.start()

    def __exit__(self, *exc):
        self.patch.stop()


def test_work_in_the_backups_own_minute_is_still_found_by_identity(inventory):
    """The store records minutes: a filename time cannot say which entries came later."""
    with FrozenMinute("2026-10-24 10:30"):
        store = InventoryStore(inventory, seed=False)
        try:
            store.receive("UPG-WIDGET", 1, "Stock", "W-A", "Early", "before backup")
        finally:
            store.engine.dispose()
        backup = backup_database(inventory, inventory.parent / "backups", reason="startup")
        store = InventoryStore(inventory, seed=False)
        try:
            store.receive("UPG-WIDGET", 2, "Stock", "W-B", "Late", "after backup, same minute")
            store.receive("UPG-WIDGET", 2, "Stock", "W-B", "Late", "after backup, same minute")
        finally:
            store.engine.dispose()
    later = rehearsal.snapshot(inventory)
    restored = rehearsal.snapshot(backup)

    dropped = rehearsal.dropped_entries(restored, later)

    assert dropped["ledger_entries"] == 2
    assert [entry["operator"] for entry in dropped["entries"]] == ["Late", "Late"]
    # Two identical rows stay two rows, and they carry the boundary minute.
    assert {entry["timestamp"] for entry in dropped["entries"]} == {"2026-10-24 10:30"}
    newer_than_minute = [e for e in dropped["entries"] if e["timestamp"] > "2026-10-24 10:30"]
    assert newer_than_minute == []  # the filename-time cutoff would have dropped both


def test_dropped_entries_describe_each_record_for_the_operator(inventory):
    backup, later = make_later_inventory(inventory)
    dropped = rehearsal.dropped_entries(rehearsal.snapshot(backup), later)
    ship = next(entry for entry in dropped["entries"] if entry["tx_type"] == "SHIP")
    assert (ship["part_number"], ship["lot_number"], ship["quantity_change"]) == (
        "UPG-WIDGET",
        "W-9",
        -3,
    )
    assert ship["shipment_number"].startswith("SHP-")


def test_the_cli_lists_what_a_restore_removed_from_the_displaced_set(inventory, capsys):
    backup, _ = make_later_inventory(inventory)
    rehearsal.restore_from_backup(inventory, backup, inventory.parent / "restore-aside", stamp="s")
    displaced = inventory.parent / "restore-aside" / "restore-aside-s" / "inventory.db"
    code = rehearsal.main(["dropped", "--kept", str(inventory), "--displaced", str(displaced)])
    out = capsys.readouterr().out
    assert code == 0
    assert "2 ledger entries" in out
    assert "UPG-WIDGET" in out
    assert "1 shipments" in out


def test_committed_records_that_exist_only_in_the_wal_need_the_whole_displaced_set(
    inventory, tmp_path
):
    """After a crash the newest committed rows can sit in the -wal file only."""
    store = InventoryStore(inventory, seed=False)  # WAL mode; connection stays open
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    try:
        store.receive("UPG-WIDGET", 4, "Stock", "W-CRASH", "Last operator")
        wal = inventory.with_name("inventory.db-wal")
        assert wal.stat().st_size > 0
        # What the disk holds at the moment of a crash: the main file plus sidecars.
        for suffix in ("", "-wal", "-shm"):
            shutil_copy(inventory.with_name("inventory.db" + suffix), crashed)
    finally:
        store.engine.dispose()
    database_only = tmp_path / "database-only"
    database_only.mkdir()
    shutil_copy(crashed / "inventory.db", database_only)

    whole = rehearsal.snapshot(crashed / "inventory.db")
    partial = rehearsal.snapshot(database_only / "inventory.db")

    assert any(row[2] == "W-CRASH" for row in whole["tables"]["lots"]["rows"].values())
    assert not any(row[2] == "W-CRASH" for row in partial["tables"]["lots"]["rows"].values())
    copied = rehearsal.copy_database_set(crashed / "inventory.db", tmp_path / "inspect")
    assert sorted(path.name for path in copied.parent.iterdir()) == [
        "inventory.db",
        "inventory.db-shm",
        "inventory.db-wal",
    ]
    assert rehearsal.digest(rehearsal.snapshot(copied)) == rehearsal.digest(whole)


def test_dropped_accepts_a_crashed_set_whose_schema_exists_only_in_the_wal(
    inventory, tmp_path, capsys
):
    """The store enables WAL before creating its schema, so a crash can leave both in it."""
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    live = tmp_path / "live" / "inventory.db"
    live.parent.mkdir()
    with closing(sqlite3.connect(live)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        script = rehearsal.FIXTURE.read_text(encoding="utf-8")
        connection.executescript(f"BEGIN;\n{script}\nCOMMIT;")
        for suffix in ("", "-wal", "-shm"):
            shutil_copy(live.with_name("inventory.db" + suffix), crashed)
    # The main file alone holds no schema, so only a WAL-aware check can accept the set.
    lone_uri = f"{(crashed / 'inventory.db').as_uri()}?immutable=1"
    with closing(sqlite3.connect(lone_uri, uri=True)) as lone:
        assert lone.execute("SELECT count(*) FROM sqlite_master").fetchone() == (0,)
    before = sqlite_files(crashed)

    code = rehearsal.main(
        ["dropped", "--kept", str(inventory), "--displaced", str(crashed / "inventory.db")]
    )

    assert code == 0, capsys.readouterr().out
    assert sqlite_files(crashed) == before


def test_verify_backup_reports_a_file_that_cannot_be_read_without_a_traceback(
    inventory, monkeypatch, capsys
):
    backup = backup_database(inventory, inventory.parent / "backups", reason="manual")

    def refused(source, destination):
        raise PermissionError(13, "Permission denied", str(source))

    monkeypatch.setattr(rehearsal.shutil, "copy2", refused)

    assert rehearsal.main(["verify-backup", str(backup)]) == 1
    assert "NOT VERIFIED" in capsys.readouterr().out


def test_dropped_reports_an_inaccessible_path_without_a_traceback(
    inventory, tmp_path, monkeypatch, capsys
):
    displaced = tmp_path / "inaccessible" / "inventory.db"
    real_is_file = Path.is_file

    def is_file(self):
        if self == displaced.resolve():
            raise PermissionError(13, "Permission denied", str(self))
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file)
    displaced.parent.mkdir()
    shutil_copy(inventory, displaced.parent)

    code = rehearsal.main(["dropped", "--kept", str(inventory), "--displaced", str(displaced)])

    assert code == 1
    assert "Permission denied" in capsys.readouterr().err


def shutil_copy(source: Path, destination: Path) -> None:
    import shutil

    shutil.copy2(source, destination)


# ------------------------------------------------ verify-backup: paths and incomplete schemas


def test_verify_backup_accepts_a_relative_path(inventory, monkeypatch, capsys):
    backup = backup_database(inventory, inventory.parent / "backups", reason="manual")
    monkeypatch.chdir(backup.parent)
    assert rehearsal.main(["verify-backup", backup.name]) == 0
    assert "verified" in capsys.readouterr().out
    assert rehearsal.verify_backup_file(Path(backup.name))["problems"] == []


def test_dropped_accepts_relative_paths(inventory, monkeypatch, capsys):
    backup, _ = make_later_inventory(inventory)
    rehearsal.restore_from_backup(inventory, backup, inventory.parent / "restore-aside", stamp="r")
    monkeypatch.chdir(inventory.parent)
    displaced = Path("restore-aside") / "restore-aside-r" / "inventory.db"
    assert rehearsal.main(["dropped", "--kept", "inventory.db", "--displaced", str(displaced)]) == 0
    assert "2 ledger entries" in capsys.readouterr().out


@pytest.mark.parametrize(
    "damage,expected",
    [
        ("DROP TABLE bom_components", "no bom_components table"),
        ("DROP TABLE settings", "no settings table"),
        ("DROP TABLE shipment_components", "no shipment_components table"),
        ("ALTER TABLE inventory_transactions DROP COLUMN notes", "inventory_transactions.notes"),
        ("ALTER TABLE settings DROP COLUMN value", "settings.value"),
    ],
)
def test_an_incomplete_backup_is_reported_not_raised(inventory, tmp_path, capsys, damage, expected):
    good = backup_database(inventory, inventory.parent / "backups", reason="manual")
    broken = tmp_path / "inventory-broken.db"
    broken.write_bytes(good.read_bytes())
    with closing(sqlite3.connect(broken)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(damage)

    report = rehearsal.verify_backup_file(broken)
    assert any(expected in problem for problem in report["problems"]), report

    assert rehearsal.main(["verify-backup", str(broken)]) == 1
    out = capsys.readouterr().out
    assert "NOT VERIFIED" in out
    assert expected in out
    assert "Traceback" not in out


def test_a_backup_with_unreadable_values_is_reported_not_raised(inventory, tmp_path, capsys):
    good = backup_database(inventory, inventory.parent / "backups", reason="manual")
    odd = tmp_path / "inventory-odd.db"
    odd.write_bytes(good.read_bytes())
    tamper(odd, "UPDATE inventory_transactions SET quantity_change = 'many' WHERE id = 5")
    assert rehearsal.main(["verify-backup", str(odd)]) == 1
    assert "NOT VERIFIED" in capsys.readouterr().out


def test_dropped_reports_an_incomplete_inventory_instead_of_raising(inventory, tmp_path, capsys):
    broken = tmp_path / "inventory.db"
    broken.write_bytes(inventory.read_bytes())
    tamper(broken, "DROP TABLE bom_components")
    code = rehearsal.main(["dropped", "--kept", str(inventory), "--displaced", str(broken)])
    assert code == 1
    assert "bom_components" in capsys.readouterr().err


def test_restore_refuses_a_backup_missing_any_table_the_inspection_needs(inventory, tmp_path):
    good = backup_database(inventory, inventory.parent / "backups", reason="manual")
    broken = tmp_path / "inventory-broken.db"
    broken.write_bytes(good.read_bytes())
    tamper(broken, "DROP TABLE bom_components")
    with pytest.raises(rehearsal.RestoreRefused, match="bom_components"):
        rehearsal.restore_from_backup(inventory, broken, inventory.parent / "restore-aside")
