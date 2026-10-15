"""Reviewed Parts imports through the public desktop API and real SQLite."""

from pathlib import Path

import pytest
from sqlalchemy import event

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore
from inventory_control.utilities import UtilityContext


class FileHost:
    def __init__(self, selection: Path | None):
        self.selection = selection

    def choose_file(self, directory, file_types=()):
        return self.selection

    def open_folder(self, path):
        pass


def launch(tmp_path, text="part_number,description\nA,Bearing\n"):
    context = UtilityContext.for_launch(tmp_path / "inventory.db")
    store = InventoryStore(context.database, seed=False)
    path = tmp_path / "parts.csv"
    path.write_text(text, encoding="utf-8")
    host = FileHost(path)
    return store, InventoryBridge(store, context, host), context, host


def test_review_confirmation_backup_and_persistence(tmp_path):
    store, bridge, context, _host = launch(tmp_path)
    review = bridge.select_import("parts")["data"]
    assert review["preview"]["can_import"] is True
    assert review["preview"]["row_count"] == 1
    assert bridge.search_parts({})["data"] == []
    request = {"review_id": review["review_id"], "confirmed": False, "operator": "Pat"}
    assert bridge.commit_import(request)["error"]["code"] == "CONFIRMATION_REQUIRED"
    result = bridge.commit_import({**request, "confirmed": True})
    assert result["ok"]
    assert result["data"]["rows_imported"] == 1
    backup = Path(result["data"]["backup_path"])
    assert backup.parent == context.backups
    assert InventoryBridge(InventoryStore(backup, seed=False)).search_parts({})["data"] == []
    assert bridge.import_status(review["review_id"])["data"]["result"] == result["data"]
    assert bridge.commit_import({**request, "confirmed": True})["error"]["code"] == "STALE"
    store.engine.dispose()
    reopened = InventoryBridge(InventoryStore(context.database, seed=False))
    assert reopened.part_detail("A")["data"]["description"] == "Bearing"


@pytest.mark.parametrize(
    "text",
    [
        "part_number,description\nA,\n",
        "part_number,description\nA,One\nA,Two\n",
        "description\nBearing\n",
        "part_number,description\n",
    ],
)
def test_invalid_rows_cannot_be_committed(tmp_path, text):
    _store, bridge, context, _host = launch(tmp_path, text)
    review = bridge.select_import("parts")["data"]
    assert review["preview"]["errors"]
    assert not review["preview"]["can_import"]
    assert not bridge.commit_import(
        {"review_id": review["review_id"], "confirmed": True, "operator": "Pat"}
    )["ok"]
    assert bridge.search_parts({})["data"] == []
    assert not context.backups.exists()


def test_ignored_fields_warn_without_blocking_import(tmp_path):
    _store, bridge, _context, _host = launch(
        tmp_path, "part_number,description,barcode\nA,Bearing,123\n"
    )
    preview = bridge.select_import("parts")["data"]["preview"]
    assert preview["can_import"]
    assert preview["warnings"][0]["field"] == "barcode"


def test_changed_file_requires_a_new_review(tmp_path):
    _store, bridge, context, host = launch(tmp_path)
    review = bridge.select_import("parts")["data"]
    host.selection.write_text("part_number,description\nA,Unreviewed\n")
    result = bridge.commit_import(
        {"review_id": review["review_id"], "confirmed": True, "operator": "Pat"}
    )
    assert result["error"]["code"] == "STALE"
    assert bridge.search_parts({})["data"] == []
    assert not context.backups.exists()


def test_cancellation_preserves_the_previous_review(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    review = bridge.select_import("parts")["data"]
    host.selection = None
    assert bridge.select_import("parts") == {"ok": True, "data": {"cancelled": True}}
    assert bridge.import_status(review["review_id"])["data"]["state"] == "reviewed"


def test_backup_failure_blocks_writes_and_retains_failed_review(tmp_path):
    _store, bridge, context, _host = launch(tmp_path)
    context.backups.write_text("Not a directory")
    review = bridge.select_import("parts")["data"]
    result = bridge.commit_import(
        {"review_id": review["review_id"], "confirmed": True, "operator": "Pat"}
    )
    assert result["error"]["code"] == "FILE_ERROR"
    assert bridge.search_parts({})["data"] == []
    assert bridge.import_status(review["review_id"])["data"]["state"] == "failed"


def test_parts_import_rolls_back_all_rows_after_a_database_failure(tmp_path):
    store, bridge, _context, _host = launch(tmp_path, "part_number,description\nA,Updated\nB,New\n")
    store.add_part("A", "Original")
    review = bridge.select_import("parts")["data"]

    def fail_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO parts"):
            raise RuntimeError("Simulated database failure")

    event.listen(store.engine, "before_cursor_execute", fail_insert)
    try:
        result = bridge.commit_import(
            {"review_id": review["review_id"], "confirmed": True, "operator": "Pat"}
        )
    finally:
        event.remove(store.engine, "before_cursor_execute", fail_insert)
    assert result["error"]["code"] == "INTERNAL"
    assert bridge.part_detail("A")["data"]["description"] == "Original"
    assert bridge.part_detail("B")["error"]["code"] == "NOT_FOUND"


def test_a_new_selection_supersedes_the_old_review(tmp_path):
    _store, bridge, _context, _host = launch(tmp_path)
    old = bridge.select_import("parts")["data"]
    new = bridge.select_import("parts")["data"]
    assert new["review_id"] != old["review_id"]
    assert (
        bridge.commit_import({"review_id": old["review_id"], "confirmed": True, "operator": "Pat"})[
            "error"
        ]["code"]
        == "STALE"
    )


def test_unreadable_or_removed_input_is_reported_and_never_written(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    review = bridge.select_import("parts")["data"]
    host.selection.unlink()
    assert bridge.select_import("parts")["error"]["code"] == "FILE_ERROR"
    assert (
        bridge.commit_import(
            {"review_id": review["review_id"], "confirmed": True, "operator": "Pat"}
        )["error"]["code"]
        == "FILE_ERROR"
    )
    assert bridge.search_parts({})["data"] == []


def test_invalid_encoding_is_a_visible_preview_issue(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    host.selection.write_bytes(b"part_number,description\nA,\xff\n")
    review = bridge.select_import("parts")["data"]
    assert not review["preview"]["can_import"]
    assert "Could not read CSV" in review["preview"]["errors"][0]["message"]


def test_import_updates_existing_fields_without_altering_stock_or_history(tmp_path):
    store, bridge, _context, _host = launch(
        tmp_path,
        "part_number,description,default_location,minimum_quantity,active\nA,Updated,Receiving,4,false\nB,New,Stock,0,true\n",
    )
    store.add_part("A", "Original")
    store.receive("A", 5, "Stock", "L1", "Pat")
    before = bridge.history({})["data"]
    review = bridge.select_import("parts")["data"]
    assert (
        bridge.commit_import(
            {"review_id": review["review_id"], "confirmed": True, "operator": "Pat"}
        )["data"]["rows_imported"]
        == 2
    )
    detail = bridge.part_detail("A")["data"]
    assert (
        detail["description"],
        detail["location"],
        detail["minimum_quantity"],
        detail["active"],
        detail["quantity"],
    ) == ("Updated", "Receiving", 4, False, 5)
    assert bridge.history({})["data"] == before
    assert bridge.part_detail("B")["data"]["description"] == "New"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"path": "input.csv"},
        {"review_id": 12},
        {"review_id": "missing", "confirmed": True, "operator": "Pat"},
    ],
)
def test_commit_rejects_invalid_or_unknown_reviews(tmp_path, payload):
    _store, bridge, _context, _host = launch(tmp_path)
    assert not bridge.commit_import(payload)["ok"]
    assert bridge.search_parts({})["data"] == []


def test_unavailable_host_or_launch_context_and_unsupported_kinds(tmp_path):
    store, bridge, context, _host = launch(tmp_path)
    assert InventoryBridge(store).select_import("parts")["error"]["code"] == "UNAVAILABLE"
    assert InventoryBridge(store, context).select_import("parts")["error"]["code"] == "UNAVAILABLE"
    assert bridge.select_import("bom")["error"]["code"] == "VALIDATION"
