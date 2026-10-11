"""Backup and folder-access use cases through the public desktop bridge.

Every case uses a real temporary SQLite inventory, disposable backup folders and a
recording host in place of the native file manager.
"""

import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

from inventory_control import config
from inventory_control.backup import backup_database
from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore
from inventory_control.utilities import UtilityContext


class RecordingHost:
    def __init__(self, failure: OSError | None = None) -> None:
        self.opened: list[Path] = []
        self.failure = failure

    def open_folder(self, path: Path) -> None:
        if self.failure is not None:
            raise self.failure
        self.opened.append(path)

    def choose_file(self, directory: Path, file_types: tuple[str, ...] = ()) -> Path | None:
        return None


def launch(tmp_path: Path, host: RecordingHost | None = None):
    """An inventory launched with --database, as the desktop launcher builds it."""
    database = tmp_path / "inventory.db"
    store = InventoryStore(database, seed=False)
    context = UtilityContext.for_launch(database)
    return store, InventoryBridge(store, context, host or RecordingHost()), context


def backup_names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("inventory-*.db"))


def stocked(store: InventoryStore) -> None:
    store.add_part("A", "Bearing", minimum_quantity=5)
    store.receive("A", 7, "Stock", "L1", "Pat")


def test_launch_context_keeps_every_location_beside_the_selected_database(tmp_path):
    inventory = tmp_path / "plant" / "inventory.db"
    inventory.parent.mkdir()
    context = UtilityContext.for_launch(inventory)
    assert context.database == inventory.resolve()
    assert context.backups == inventory.parent.resolve() / "backups"
    assert context.exports == inventory.parent.resolve() / "exports"
    assert context.logs == inventory.parent.resolve() / "logs"


def test_default_launch_uses_the_invsys_home_locations():
    context = UtilityContext.for_launch()
    assert (context.database, context.backups, context.exports, context.logs) == (
        config.DB_PATH,
        config.BACKUP_DIR,
        config.EXPORT_DIR,
        config.LOG_DIR,
    )
    assert os.environ["INVSYS_HOME"]
    assert context.database.is_relative_to(Path(os.environ["INVSYS_HOME"]).resolve())


def test_context_reports_launch_locations_and_no_backup_yet(tmp_path):
    _store, bridge, context = launch(tmp_path)
    result = bridge.utility_context()
    assert result == {
        "ok": True,
        "data": {
            "database": str(context.database),
            "database_exists": True,
            "backup_dir": str(context.backups),
            "export_dir": str(context.exports),
            "log_dir": str(context.logs),
            "latest_backup": None,
            "backup_count": 0,
            "backup_retention": 20,
            "backup_error": None,
        },
    }
    json.dumps(result, allow_nan=False)


def test_manual_backup_contains_the_inventory_and_is_reported_as_latest(tmp_path):
    store, bridge, context = launch(tmp_path)
    stocked(store)
    result = bridge.create_backup()
    assert result["ok"] is True
    created = result["data"]["created"]
    backup = context.backups / created["name"]
    assert created["name"].startswith("inventory-")
    assert created["name"].endswith("-manual.db")
    assert created["path"] == str(backup)
    assert created["size_bytes"] == backup.stat().st_size > 0
    assert result["data"]["context"]["latest_backup"] == created
    assert result["data"]["context"]["backup_count"] == 1
    assert bridge.utility_context()["data"]["latest_backup"] == created
    json.dumps(result, allow_nan=False)

    # Reopen the backup file itself: it carries the Part, Lot balance and ledger row.
    with closing(sqlite3.connect(f"{backup.as_uri()}?mode=ro&immutable=1", uri=True)) as copy:
        assert copy.execute("SELECT part_number FROM parts").fetchall() == [("A",)]
        assert copy.execute("SELECT SUM(quantity) FROM inventory_balances").fetchone() == (7,)
        assert copy.execute("SELECT COUNT(*) FROM inventory_transactions").fetchone() == (1,)
    reopened = InventoryStore(backup, seed=False)
    assert reopened.part_detail("A")["quantity"] == 7


def test_backup_is_a_point_in_time_copy_and_leaves_the_live_inventory_untouched(tmp_path):
    store, bridge, context = launch(tmp_path)
    stocked(store)
    first = bridge.create_backup()["data"]["created"]
    store.receive("A", 3, "Stock", "L2", "Pat")
    second = bridge.create_backup()["data"]["created"]
    assert first["name"] != second["name"]
    assert backup_names(context.backups) == sorted([first["name"], second["name"]])
    assert bridge.utility_context()["data"]["latest_backup"] == second
    assert bridge.utility_context()["data"]["backup_count"] == 2
    older = InventoryStore(context.backups / first["name"], seed=False)
    assert older.part_detail("A")["quantity"] == 7
    assert (
        InventoryStore(context.backups / second["name"], seed=False).part_detail("A")["quantity"]
        == 10
    )
    assert store.part_detail("A")["quantity"] == 10


def test_manual_backups_preserve_startup_backups_and_apply_retention(tmp_path):
    store, bridge, context = launch(tmp_path)
    stocked(store)
    startup = backup_database(context.database, context.backups, reason="startup")
    assert startup is not None
    # Age the startup backup plus 19 prior files, so the 21st file exceeds retention.
    aged = [
        context.backups / f"inventory-200001{index + 1:02d}-000000-old.db" for index in range(19)
    ]
    for index, old in enumerate(aged):
        old.write_bytes(b"old")
        os.utime(old, (1_000_000 + index, 1_000_000 + index))
    os.utime(startup, (2_000_000, 2_000_000))
    oldest = aged[0]
    assert oldest.exists()
    assert len(backup_names(context.backups)) == 20

    created = bridge.create_backup()["data"]["created"]
    names = backup_names(context.backups)
    assert len(names) == 20
    assert created["name"] in names
    assert startup.name in names
    assert not oldest.exists()
    assert bridge.utility_context()["data"]["backup_count"] == 20


def test_backups_stay_with_their_selected_inventory(tmp_path):
    first_store, first_bridge, first = launch(tmp_path / "one")
    second_store, second_bridge, second = launch(tmp_path / "two")
    stocked(first_store)
    second_store.add_part("B", "Cable")
    first_bridge.create_backup()
    assert len(backup_names(first.backups)) == 1
    assert not second.backups.exists()
    assert second_bridge.utility_context()["data"]["latest_backup"] is None
    second_bridge.create_backup()
    with closing(sqlite3.connect(next(second.backups.glob("inventory-*.db")))) as copy:
        assert copy.execute("SELECT part_number FROM parts").fetchall() == [("B",)]
    assert len(backup_names(first.backups)) == 1


def test_backup_without_a_database_file_reports_the_missing_database(tmp_path):
    _store, bridge, context = launch(tmp_path)
    context.database.unlink()
    state = bridge.utility_context()["data"]
    assert state["database_exists"] is False
    result = bridge.create_backup()
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"
    assert str(context.database) in result["error"]["message"]
    assert not context.backups.exists()


def test_a_database_that_cannot_be_backed_up_faithfully_is_not_reported_as_a_backup(tmp_path):
    store, bridge, context = launch(tmp_path)
    store.engine.dispose()
    for sidecar in context.database.parent.glob("inventory.db-*"):
        sidecar.unlink()
    context.database.write_bytes(b"this is not a sqlite database" * 100)
    result = bridge.create_backup()
    assert result["ok"] is False
    assert result["error"]["code"] == "FILE_ERROR"
    assert "could not be verified" in result["error"]["message"]
    assert backup_names(context.backups) == []
    assert bridge.utility_context()["data"]["latest_backup"] is None


def test_backup_file_failures_are_reported_and_leave_no_backup(tmp_path):
    _store, bridge, context = launch(tmp_path)
    context.backups.write_text("not a folder", encoding="utf-8")
    result = bridge.create_backup()
    assert result["ok"] is False
    assert result["error"]["code"] == "FILE_ERROR"
    assert "backup" in result["error"]["message"].lower()
    assert context.backups.read_text(encoding="utf-8") == "not a folder"
    state = bridge.utility_context()
    assert state["ok"] is True
    assert state["data"]["latest_backup"] is None
    assert state["data"]["backup_error"]


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for the current user",
)
def test_unwritable_backup_folder_is_reported_without_a_partial_backup(tmp_path):
    _store, bridge, context = launch(tmp_path)
    context.backups.mkdir()
    context.backups.chmod(0o500)
    try:
        result = bridge.create_backup()
        assert result["ok"] is False
        assert result["error"]["code"] == "FILE_ERROR"
        assert backup_names(context.backups) == []
    finally:
        context.backups.chmod(0o700)


@pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for the current user",
)
def test_unreadable_backup_folder_is_not_shown_as_having_no_backups(tmp_path):
    _store, bridge, context = launch(tmp_path)
    context.backups.mkdir()
    context.backups.chmod(0)
    try:
        state = bridge.utility_context()["data"]
    finally:
        context.backups.chmod(0o700)
    assert state["latest_backup"] is None
    assert state["backup_error"]


def test_open_folder_uses_the_selected_inventory_locations(tmp_path):
    host = RecordingHost()
    _store, bridge, context = launch(tmp_path, host)
    assert bridge.open_folder("backups")["data"] == {"folder": str(context.backups)}
    assert bridge.open_folder("exports")["data"] == {"folder": str(context.exports)}
    # A folder that does not exist yet is created so the file manager has a target.
    assert host.opened == [context.backups, context.exports]
    assert context.backups.is_dir()
    assert context.exports.is_dir()


def test_open_folder_failure_is_visible_and_not_a_success(tmp_path):
    host = RecordingHost(failure=OSError("No file manager is available"))
    _store, bridge, context = launch(tmp_path, host)
    result = bridge.open_folder("exports")
    assert result["ok"] is False
    assert result["error"]["code"] == "FILE_ERROR"
    assert "No file manager is available" in result["error"]["message"]
    assert str(context.exports) in result["error"]["message"]


def test_open_folder_cannot_be_directed_at_arbitrary_paths(tmp_path):
    host = RecordingHost()
    _store, bridge, _context = launch(tmp_path, host)
    for kind in ("logs", "/etc", "../..", "", "BACKUPS", 3, None, {"kind": "backups"}):
        result = bridge.open_folder(kind)
        assert result["ok"] is False
        assert result["error"]["code"] == "VALIDATION"
    assert host.opened == []


def test_open_folder_reports_a_folder_that_cannot_be_created(tmp_path):
    host = RecordingHost()
    _store, bridge, context = launch(tmp_path, host)
    context.exports.write_text("blocked", encoding="utf-8")
    result = bridge.open_folder("exports")
    assert result["ok"] is False
    assert result["error"]["code"] == "FILE_ERROR"
    assert host.opened == []


def test_utilities_are_unavailable_without_a_launch_context(tmp_path):
    bridge = InventoryBridge(InventoryStore(tmp_path / "inventory.db", seed=False))
    for result in (bridge.utility_context(), bridge.create_backup(), bridge.open_folder("backups")):
        assert result["ok"] is False
        assert result["error"]["code"] == "UNAVAILABLE"


def test_utility_operations_are_not_exposed_with_native_internals(tmp_path):
    """pywebview publishes every public attribute of the bridge, recursively."""
    _store, bridge, _context = launch(tmp_path)
    public = {name for name in vars(bridge) if not name.startswith("_")}
    assert public == set()
