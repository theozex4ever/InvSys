"""Reviewed Inventory receipt imports through the public desktop API and real SQLite."""

from pathlib import Path

import pytest
from sqlalchemy import event

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore
from inventory_control.utilities import UtilityContext

HEADER = "part_number,location,lot_number,quantity"


class FileHost:
    def __init__(self, selection: Path | None):
        self.selection = selection
        self.directories: list[Path] = []

    def choose_file(self, directory, file_types=()):
        self.directories.append(directory)
        return self.selection

    def open_folder(self, path):
        pass


def launch(tmp_path, text=f"{HEADER}\nA,Stock,L1,5\n"):
    context = UtilityContext.for_launch(tmp_path / "inventory.db")
    store = InventoryStore(context.database, seed=False)
    store.add_part("A", "Bearing")
    store.add_part("B", "Cable")
    path = tmp_path / "receipts.csv"
    path.write_text(text, encoding="utf-8")
    host = FileHost(path)
    return store, InventoryBridge(store, context, host), context, host


def commit(bridge, review, **extra):
    return bridge.commit_import(
        {"review_id": review["review_id"], "confirmed": True, "operator": "Pat", **extra}
    )


def balances(bridge, part="A"):
    part = bridge.stock_context(part)["data"]["part"]
    return {(b["location"], b["lot_number"]): b["quantity"] for b in part["balances"]}


def records(bridge):
    return bridge.history({})["data"]["records"]


def test_reviewed_receipts_post_attributed_ledger_rows_after_a_verified_backup(tmp_path):
    store, bridge, context, host = launch(
        tmp_path,
        "part_number,location,lot_number,quantity,reference,notes\n"
        "a,Stock, l1 ,5,PO-7,Dock 2\nB,Receiving,L9,3,,\n",
    )
    review = bridge.select_import("inventory")["data"]
    assert host.directories == [context.database.parent]
    assert (review["preview"]["kind"], review["preview"]["row_count"]) == ("inventory", 2)
    assert review["preview"]["can_import"] is True
    assert records(bridge) == []
    request = {"review_id": review["review_id"], "confirmed": False, "operator": "Pat"}
    assert bridge.commit_import(request)["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert records(bridge) == []

    result = commit(bridge, review)

    assert result["ok"]
    assert (result["data"]["kind"], result["data"]["rows_imported"]) == ("inventory", 2)
    backup = Path(result["data"]["backup_path"])
    assert backup.parent == context.backups
    assert records(InventoryBridge(InventoryStore(backup, seed=False))) == []
    assert balances(bridge) == {("Stock", "L1"): 5}
    assert balances(bridge, "B") == {("Receiving", "L9"): 3}
    receipts = {row["part_number"]: row for row in records(bridge)}
    assert {row["tx_type"] for row in receipts.values()} == {"RECEIVE"}
    assert {row["operator"] for row in receipts.values()} == {"Pat"}
    assert (receipts["A"]["reference"], receipts["A"]["notes"]) == ("PO-7", "Dock 2")
    assert receipts["B"]["reference"] == "CSV import"
    assert bridge.import_status(review["review_id"])["data"]["result"] == result["data"]
    assert commit(bridge, review)["error"]["code"] == "STALE"
    assert balances(bridge) == {("Stock", "L1"): 5}
    store.engine.dispose()
    reopened = InventoryBridge(InventoryStore(context.database, seed=False))
    assert balances(reopened) == {("Stock", "L1"): 5}
    assert len(records(reopened)) == 2


@pytest.mark.parametrize(
    "row, field",
    [
        ("A,Stock,,5", "lot_number"),
        ("A,Stock,   ,5", "lot_number"),
        ("MISSING,Stock,L1,5", "part_number"),
        ("A,Nowhere,L1,5", "location"),
        ("A,Stock,L1,0", "quantity"),
        ("A,Stock,L1,-2", "quantity"),
        ("A,Stock,L1,1.5", "quantity"),
        ("A,Stock,L1,many", "quantity"),
        ("A,Stock,L1,2147483648", "quantity"),
        ("A,Stock,L1,5\na,Stock,l1,2", "lot_number"),
    ],
)
def test_invalid_receipt_rows_are_reported_and_cannot_change_stock(tmp_path, row, field):
    _store, bridge, context, _host = launch(tmp_path, f"{HEADER}\nB,Stock,L2,1\n{row}\n")
    review = bridge.select_import("inventory")["data"]
    preview = review["preview"]
    assert field in {issue["field"] for issue in preview["errors"]}
    assert all(issue["row_number"] > 2 for issue in preview["errors"])
    assert not preview["can_import"]
    assert not commit(bridge, review)["ok"]
    assert records(bridge) == []
    assert not context.backups.exists()


@pytest.mark.parametrize(
    "text", ["part_number,location,quantity\nA,Stock,5\n", f"{HEADER}\n", "", "﻿"]
)
def test_malformed_files_are_blocked_before_commit(tmp_path, text):
    _store, bridge, _context, _host = launch(tmp_path, text)
    review = bridge.select_import("inventory")["data"]
    assert review["preview"]["errors"]
    assert not commit(bridge, review)["ok"]
    assert records(bridge) == []


def test_columns_that_are_not_imported_warn_without_blocking(tmp_path):
    _store, bridge, _context, _host = launch(
        tmp_path, f"{HEADER},description,operator\nA,Stock,L1,5,Bearing,Sam\n"
    )
    review = bridge.select_import("inventory")["data"]
    assert [issue["field"] for issue in review["preview"]["warnings"]] == [
        "description",
        "operator",
    ]
    assert review["preview"]["can_import"]
    commit(bridge, review)
    assert [row["operator"] for row in records(bridge)] == ["Pat"]


def test_inactive_parts_are_rejected_in_review(tmp_path):
    store, bridge, _context, _host = launch(tmp_path)
    store.set_part_active("A", False)
    preview = bridge.select_import("inventory")["data"]["preview"]
    assert [issue["field"] for issue in preview["errors"]] == ["part_number"]
    assert "inactive" in preview["errors"][0]["message"]


def test_commit_validates_again_and_rejects_a_review_invalidated_by_catalog_changes(tmp_path):
    store, bridge, context, _host = launch(tmp_path)
    review = bridge.select_import("inventory")["data"]
    store.set_part_active("A", False)
    result = commit(bridge, review)
    assert result["error"]["code"] == "STALE"
    assert "Row 2" in result["error"]["message"]
    assert records(bridge) == []
    assert not context.backups.exists()
    assert bridge.import_status(review["review_id"])["data"]["state"] == "failed"


def test_changed_file_requires_a_new_review(tmp_path):
    _store, bridge, context, host = launch(tmp_path)
    review = bridge.select_import("inventory")["data"]
    host.selection.write_text(f"{HEADER}\nA,Stock,L1,500\n", encoding="utf-8")
    assert commit(bridge, review)["error"]["code"] == "STALE"
    assert records(bridge) == []
    assert not context.backups.exists()


def test_removed_input_is_reported_and_never_written(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    review = bridge.select_import("inventory")["data"]
    host.selection.unlink()
    result = commit(bridge, review)
    assert result["error"]["code"] == "FILE_ERROR"
    assert "no stock changes" in result["error"]["message"]
    assert records(bridge) == []


def test_backup_failure_blocks_receipts_and_retains_the_failed_review(tmp_path):
    _store, bridge, context, _host = launch(tmp_path)
    context.backups.write_text("Not a directory")
    review = bridge.select_import("inventory")["data"]
    assert commit(bridge, review)["error"]["code"] == "FILE_ERROR"
    assert records(bridge) == []
    assert balances(bridge) == {}
    assert bridge.import_status(review["review_id"])["data"]["state"] == "failed"


def test_a_database_failure_rolls_back_every_receipt_row(tmp_path):
    store, bridge, _context, _host = launch(tmp_path, f"{HEADER}\nA,Stock,L1,5\nB,Stock,L2,3\n")
    review = bridge.select_import("inventory")["data"]
    inserted = []

    def fail_second_receipt(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO inventory_transactions"):
            inserted.append(statement)
            if len(inserted) == 2:
                raise RuntimeError("Simulated database failure")

    event.listen(store.engine, "before_cursor_execute", fail_second_receipt)
    try:
        result = commit(bridge, review)
    finally:
        event.remove(store.engine, "before_cursor_execute", fail_second_receipt)
    assert result["error"]["code"] == "INTERNAL"
    assert records(bridge) == []
    assert balances(bridge) == {}
    assert balances(bridge, "B") == {}
    assert bridge.import_status(review["review_id"])["data"]["state"] == "failed"


def test_import_kinds_keep_independent_reviews(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    receipts = bridge.select_import("inventory")["data"]
    parts_csv = tmp_path / "parts.csv"
    parts_csv.write_text("part_number,description\nC,Gear\n", encoding="utf-8")
    host.selection = parts_csv
    parts = bridge.select_import("parts")["data"]
    assert parts["preview"]["kind"] == "parts"
    assert bridge.import_status(receipts["review_id"])["data"]["state"] == "reviewed"
    assert commit(bridge, receipts)["data"]["kind"] == "inventory"
    assert commit(bridge, parts)["data"]["kind"] == "parts"
    newer = bridge.select_import("parts")["data"]
    assert bridge.import_status(newer["review_id"])["data"]["state"] == "reviewed"
    host.selection = tmp_path / "receipts.csv"
    replaced = bridge.select_import("inventory")["data"]
    bridge.select_import("inventory")
    assert bridge.import_status(replaced["review_id"])["data"]["state"] == "superseded"
    assert bridge.import_status(newer["review_id"])["data"]["state"] == "reviewed"


def test_cancellation_preserves_the_previous_receipt_review(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    review = bridge.select_import("inventory")["data"]
    host.selection = None
    assert bridge.select_import("inventory") == {"ok": True, "data": {"cancelled": True}}
    assert bridge.import_status(review["review_id"])["data"]["state"] == "reviewed"
    assert records(bridge) == []


def test_receipt_import_requires_an_operator(tmp_path):
    _store, bridge, _context, _host = launch(tmp_path)
    review = bridge.select_import("inventory")["data"]
    assert commit(bridge, review, operator="  ")["error"]["code"] == "VALIDATION"
    assert bridge.import_status(review["review_id"])["data"]["state"] == "reviewed"
    assert records(bridge) == []


def test_bom_import_is_not_yet_exposed(tmp_path):
    _store, bridge, _context, _host = launch(tmp_path)
    assert bridge.select_import("bom")["error"]["code"] == "VALIDATION"
