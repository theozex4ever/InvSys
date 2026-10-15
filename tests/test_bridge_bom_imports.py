"""Reviewed BOM definition imports through the public desktop API and real SQLite."""

from pathlib import Path

import pytest
from sqlalchemy import event

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore
from inventory_control.utilities import UtilityContext

HEADER = "parent_part_number,component_part_number,quantity_per"
NESTED = f"{HEADER}\nKIT,SUB,2\nSUB,LEAF,3\nKIT,LEAF,1\n"


class FileHost:
    def __init__(self, selection: Path | None):
        self.selection = selection
        self.directories: list[Path] = []

    def choose_file(self, directory, file_types=()):
        self.directories.append(directory)
        return self.selection

    def open_folder(self, path):
        pass


def launch(tmp_path, text=NESTED):
    context = UtilityContext.for_launch(tmp_path / "inventory.db")
    store = InventoryStore(context.database, seed=False)
    for number in ("KIT", "SUB", "LEAF", "BOLT"):
        store.add_part(number, f"{number} part")
    path = tmp_path / "bom.csv"
    path.write_text(text, encoding="utf-8")
    host = FileHost(path)
    return store, InventoryBridge(store, context, host), context, host


def commit(bridge, review, **extra):
    return bridge.commit_import(
        {"review_id": review["review_id"], "confirmed": True, "operator": "Pat", **extra}
    )


def links(bridge, parent):
    return {
        c["part_number"]: c["quantity_per"]
        for c in bridge.bom_definition(parent)["data"]["components"]
    }


def all_links(bridge):
    return {parent: links(bridge, parent) for parent in ("KIT", "SUB", "LEAF", "BOLT")}


def records(bridge):
    return bridge.history({})["data"]["records"]


def stock(bridge, part):
    return bridge.part_detail(part)["data"]["quantity"]


def test_nested_and_shared_definitions_import_after_a_verified_backup_and_persist(tmp_path):
    store, bridge, context, host = launch(tmp_path)
    store.receive("LEAF", 20, "Stock", "A", "Setup")
    review = bridge.select_import("bom")["data"]
    assert host.directories == [context.database.parent]
    assert (review["preview"]["kind"], review["preview"]["row_count"]) == ("bom", 3)
    assert (review["preview"]["valid_count"], review["preview"]["can_import"]) == (3, True)
    ledger_before = records(bridge)
    request = {"review_id": review["review_id"], "confirmed": False, "operator": "Pat"}
    assert bridge.commit_import(request)["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert all_links(bridge) == {"KIT": {}, "SUB": {}, "LEAF": {}, "BOLT": {}}
    assert not context.backups.exists()

    result = commit(bridge, review)

    assert result["ok"]
    assert (result["data"]["kind"], result["data"]["rows_imported"]) == ("bom", 3)
    backup = Path(result["data"]["backup_path"])
    assert backup.parent == context.backups
    # The backup is taken before the definitions are written.
    assert all_links(InventoryBridge(InventoryStore(backup, seed=False)))["KIT"] == {}
    assert all_links(bridge) == {
        "KIT": {"LEAF": 1, "SUB": 2},
        "SUB": {"LEAF": 3},
        "LEAF": {},
        "BOLT": {},
    }
    # Python derives nested requirements from the imported definitions.
    explored = bridge.explore_bom({"part_number": "KIT", "quantity": 2, "location": "Stock"})
    assert [
        (r["part_number"], r["quantity_required"]) for r in explored["data"]["requirements"]
    ] == [("LEAF", 14)]
    # Importing definitions never touches stock or the ledger.
    assert records(bridge) == ledger_before
    assert stock(bridge, "LEAF") == 20
    assert bridge.import_status(review["review_id"])["data"]["result"] == result["data"]
    assert commit(bridge, review)["error"]["code"] == "STALE"
    store.engine.dispose()
    reopened = InventoryBridge(InventoryStore(context.database, seed=False))
    assert links(reopened, "KIT") == {"LEAF": 1, "SUB": 2}


def test_reimporting_updates_links_without_removing_others(tmp_path):
    store, bridge, _context, host = launch(tmp_path)
    store.add_bom_component("KIT", "SUB", 9)
    store.add_bom_component("KIT", "BOLT", 4)
    review = bridge.select_import("bom")["data"]
    assert [(w["row_number"], w["field"], w["level"]) for w in review["preview"]["warnings"]] == [
        (2, "quantity_per", "warning")
    ]
    assert "from 9 to 2" in review["preview"]["warnings"][0]["message"]
    assert review["preview"]["can_import"]
    assert commit(bridge, review)["ok"]
    assert links(bridge, "KIT") == {"BOLT": 4, "LEAF": 1, "SUB": 2}
    # An unchanged definition is not a warning.
    again = bridge.select_import("bom")["data"]
    assert again["preview"]["warnings"] == []
    assert commit(bridge, again)["ok"]
    assert links(bridge, "KIT") == {"BOLT": 4, "LEAF": 1, "SUB": 2}
    assert host.selection.exists()


@pytest.mark.parametrize(
    "row, field",
    [
        ("GHOST,SUB,1", "parent_part_number"),
        ("KIT,GHOST,1", "component_part_number"),
        (",SUB,1", "parent_part_number"),
        ("KIT,,1", "component_part_number"),
        ("KIT,KIT,1", "component_part_number"),
        ("KIT,SUB,0", "quantity_per"),
        ("KIT,SUB,-2", "quantity_per"),
        ("KIT,SUB,1.5", "quantity_per"),
        ("KIT,SUB,many", "quantity_per"),
        ("KIT,SUB,", "quantity_per"),
        ("KIT,SUB,2147483648", "quantity_per"),
        ("KIT,SUB,1\nkit, sub ,2", "component_part_number"),
    ],
)
def test_invalid_rows_are_reported_and_cannot_change_definitions(tmp_path, row, field):
    _store, bridge, context, _host = launch(tmp_path, f"{HEADER}\nSUB,LEAF,1\n{row}\n")
    review = bridge.select_import("bom")["data"]
    preview = review["preview"]
    assert field in {issue["field"] for issue in preview["errors"]}
    assert all(issue["row_number"] > 2 for issue in preview["errors"])
    assert preview["valid_count"] < preview["row_count"]
    assert not preview["can_import"]
    assert not commit(bridge, review)["ok"]
    assert all_links(bridge)["SUB"] == {}
    assert not context.backups.exists()


def test_inactive_parts_are_blocked_in_review_rather_than_after_the_backup(tmp_path):
    store, bridge, context, _host = launch(tmp_path)
    store.set_part_active("LEAF", False)
    review = bridge.select_import("bom")["data"]
    errors = review["preview"]["errors"]
    assert sorted(e["row_number"] for e in errors) == [3, 4]
    assert all("inactive" in e["message"] for e in errors)
    assert not commit(bridge, review)["ok"]
    assert not context.backups.exists()


def test_cycles_are_rejected_with_every_offending_row_and_other_rows_stay_valid(tmp_path):
    store, bridge, context, _host = launch(
        tmp_path, f"{HEADER}\nKIT,SUB,1\nSUB,LEAF,1\nLEAF,KIT,1\nKIT,BOLT,1\nBOLT,KIT,2\n"
    )
    store.add_bom_component("BOLT", "LEAF", 1)
    preview = bridge.select_import("bom")["data"]["preview"]
    cyclic = sorted(e["row_number"] for e in preview["errors"] if "circular" in e["message"])
    # KIT->SUB->LEAF->KIT and the KIT<->BOLT pair; BOLT->LEAF is existing and acyclic.
    assert cyclic == [2, 3, 4, 5, 6]
    assert (preview["valid_count"], preview["can_import"]) == (0, False)
    assert all_links(bridge) == {"KIT": {}, "SUB": {}, "LEAF": {}, "BOLT": {"LEAF": 1}}
    assert not context.backups.exists()


def test_a_cycle_through_existing_definitions_is_rejected(tmp_path):
    store, bridge, _context, _host = launch(tmp_path, f"{HEADER}\nLEAF,KIT,1\n")
    store.add_bom_component("KIT", "SUB", 1)
    store.add_bom_component("SUB", "LEAF", 1)
    review = bridge.select_import("bom")["data"]
    assert [e["message"] for e in review["preview"]["errors"]] == [
        "This component would create a circular BOM."
    ]
    assert not commit(bridge, review)["ok"]
    assert links(bridge, "LEAF") == {}


def test_a_long_definition_chain_is_validated_without_recursion_limits(tmp_path):
    context = UtilityContext.for_launch(tmp_path / "inventory.db")
    store = InventoryStore(context.database, seed=False)
    depth = 1200
    rows = []
    for index in range(depth + 1):
        store.add_part(f"P{index}", f"Part {index}")
    for index in range(depth):
        rows.append(f"P{index},P{index + 1},1")
    rows.append(f"P{depth},P0,1")
    path = tmp_path / "chain.csv"
    path.write_text(f"{HEADER}\n" + "\n".join(rows) + "\n", encoding="utf-8")
    bridge = InventoryBridge(store, context, FileHost(path))
    preview = bridge.select_import("bom")["data"]["preview"]
    assert len(preview["errors"]) == depth + 1
    assert all("circular" in e["message"] for e in preview["errors"])
    path.write_text(f"{HEADER}\n" + "\n".join(rows[:-1]) + "\n", encoding="utf-8")
    assert bridge.select_import("bom")["data"]["preview"]["can_import"]


@pytest.mark.parametrize(
    "text",
    [
        "parent_part_number,component_part_number\nKIT,SUB\n",
        f"{HEADER}\n",
        "",
        "﻿",
    ],
)
def test_malformed_files_are_blocked_before_commit(tmp_path, text):
    _store, bridge, context, _host = launch(tmp_path, text)
    review = bridge.select_import("bom")["data"]
    assert review["preview"]["errors"]
    assert not commit(bridge, review)["ok"]
    assert all_links(bridge)["KIT"] == {}
    assert not context.backups.exists()


@pytest.mark.parametrize(
    "text",
    [
        f"{HEADER},quantity_per\nKIT,SUB,2,900\n",
        f"{HEADER}\nKIT,SUB,1,000\n",
        f"{HEADER},\nKIT,SUB,1,7\n",
        f'{HEADER},notes\nKIT,SUB,1,"unterminated\n',
        f'{HEADER},notes\nKIT,SUB,1,"x"y\n',
    ],
)
def test_ambiguous_csv_structure_cannot_change_definitions(tmp_path, text):
    _store, bridge, context, _host = launch(tmp_path, text)
    review = bridge.select_import("bom")["data"]
    assert review["preview"]["errors"]
    assert not review["preview"]["can_import"]
    assert not commit(bridge, review)["ok"]
    assert all_links(bridge)["KIT"] == {}
    assert not context.backups.exists()


def test_columns_that_are_not_imported_warn_without_blocking(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    host.selection.write_bytes(
        f"﻿{HEADER},description,notes\r\nKIT,SUB,2,Sub,x\r\n\r\nSUB,LEAF,3,,\r\n".encode()
    )
    review = bridge.select_import("bom")["data"]
    assert [issue["field"] for issue in review["preview"]["warnings"]] == [
        "description",
        "notes",
    ]
    assert review["preview"]["can_import"]
    assert commit(bridge, review)["data"]["rows_imported"] == 2
    assert links(bridge, "KIT") == {"SUB": 2}


def test_commit_validates_again_and_rejects_a_review_invalidated_by_definition_changes(tmp_path):
    store, bridge, context, _host = launch(tmp_path, f"{HEADER}\nSUB,LEAF,3\n")
    review = bridge.select_import("bom")["data"]
    assert review["preview"]["can_import"]
    # Another operator makes the reviewed link circular after the review.
    store.add_bom_component("LEAF", "SUB", 1)
    result = commit(bridge, review)
    assert result["error"]["code"] == "STALE"
    assert "Row 2" in result["error"]["message"]
    assert links(bridge, "SUB") == {}
    assert not context.backups.exists()
    assert bridge.import_status(review["review_id"])["data"]["state"] == "failed"


def test_commit_rejects_a_review_whose_parts_were_deactivated(tmp_path):
    store, bridge, context, _host = launch(tmp_path)
    review = bridge.select_import("bom")["data"]
    store.set_part_active("SUB", False)
    assert commit(bridge, review)["error"]["code"] == "STALE"
    assert all_links(bridge)["KIT"] == {}
    assert not context.backups.exists()


def test_changed_file_requires_a_new_review(tmp_path):
    _store, bridge, context, host = launch(tmp_path)
    review = bridge.select_import("bom")["data"]
    host.selection.write_text(f"{HEADER}\nKIT,SUB,500\n", encoding="utf-8")
    assert commit(bridge, review)["error"]["code"] == "STALE"
    assert all_links(bridge)["KIT"] == {}
    assert not context.backups.exists()


def test_removed_input_is_reported_and_never_written(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    review = bridge.select_import("bom")["data"]
    host.selection.unlink()
    result = commit(bridge, review)
    assert result["error"]["code"] == "FILE_ERROR"
    assert "no BOM definition changes" in result["error"]["message"]
    assert all_links(bridge)["KIT"] == {}


def test_backup_failure_blocks_the_import_and_retains_the_failed_review(tmp_path):
    _store, bridge, context, _host = launch(tmp_path)
    context.backups.write_text("Not a directory")
    review = bridge.select_import("bom")["data"]
    result = commit(bridge, review)
    assert result["error"]["code"] == "FILE_ERROR"
    assert "no BOM definition changes" in result["error"]["message"]
    assert all_links(bridge)["KIT"] == {}
    assert bridge.import_status(review["review_id"])["data"]["state"] == "failed"
    assert commit(bridge, review)["error"]["code"] == "STALE"


def test_a_database_failure_rolls_back_every_link_and_is_never_retried(tmp_path):
    store, bridge, _context, _host = launch(tmp_path)
    store.add_bom_component("KIT", "BOLT", 5)
    review = bridge.select_import("bom")["data"]
    inserted = []

    def fail_second_link(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO bom_components"):
            inserted.append(statement)
            if len(inserted) == 2:
                raise RuntimeError("Simulated database failure")

    event.listen(store.engine, "before_cursor_execute", fail_second_link)
    try:
        result = commit(bridge, review)
    finally:
        event.remove(store.engine, "before_cursor_execute", fail_second_link)
    assert result["error"]["code"] == "INTERNAL"
    assert all_links(bridge) == {"KIT": {"BOLT": 5}, "SUB": {}, "LEAF": {}, "BOLT": {}}
    assert bridge.import_status(review["review_id"])["data"]["state"] == "failed"
    assert commit(bridge, review)["error"]["code"] == "STALE"
    assert all_links(bridge)["SUB"] == {}


def test_import_kinds_keep_independent_reviews(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    definitions = bridge.select_import("bom")["data"]
    parts_csv = tmp_path / "parts.csv"
    parts_csv.write_text("part_number,description\nC,Gear\n", encoding="utf-8")
    host.selection = parts_csv
    parts = bridge.select_import("parts")["data"]
    assert bridge.import_status(definitions["review_id"])["data"]["state"] == "reviewed"
    assert commit(bridge, parts)["data"]["kind"] == "parts"
    assert commit(bridge, definitions)["data"]["kind"] == "bom"
    host.selection = tmp_path / "bom.csv"
    first = bridge.select_import("bom")["data"]
    bridge.select_import("bom")
    assert bridge.import_status(first["review_id"])["data"]["state"] == "superseded"
    assert commit(bridge, first)["error"]["code"] == "STALE"


def test_cancellation_preserves_the_previous_bom_review(tmp_path):
    _store, bridge, _context, host = launch(tmp_path)
    review = bridge.select_import("bom")["data"]
    host.selection = None
    assert bridge.select_import("bom") == {"ok": True, "data": {"cancelled": True}}
    assert bridge.import_status(review["review_id"])["data"]["state"] == "reviewed"
    assert all_links(bridge)["KIT"] == {}


def test_bom_import_requires_an_operator(tmp_path):
    _store, bridge, _context, _host = launch(tmp_path)
    review = bridge.select_import("bom")["data"]
    assert commit(bridge, review, operator="  ")["error"]["code"] == "VALIDATION"
    assert bridge.import_status(review["review_id"])["data"]["state"] == "reviewed"
    assert all_links(bridge)["KIT"] == {}


def test_unknown_import_kinds_are_rejected(tmp_path):
    _store, bridge, _context, _host = launch(tmp_path)
    assert bridge.select_import("shipments")["error"]["code"] == "VALIDATION"


def bom_shipment(bridge):
    draft = dict(
        part_number="KIT",
        quantity=2,
        location="Stock",
        operator="Pat",
        recipient="Customer",
        reference="ORDER-BOM",
    )
    return draft, bridge.preview_bom_ship(draft)["data"]


def stocked(tmp_path):
    store, bridge, context, host = launch(tmp_path)
    store.add_bom_component("KIT", "SUB", 2)
    store.add_bom_component("SUB", "LEAF", 3)
    store.add_bom_component("KIT", "LEAF", 1)
    store.receive("KIT", 10, "Stock", "PARENT", "Setup")
    store.receive("SUB", 10, "Stock", "INTERMEDIATE", "Setup")
    store.receive("LEAF", 5, "Stock", "A", "Setup")
    store.receive("LEAF", 30, "Stock", "B", "Setup")
    return store, bridge, context, host


def test_historical_shipment_snapshots_survive_a_later_definition_import(tmp_path):
    _store, bridge, context, host = stocked(tmp_path)
    draft, plan = bom_shipment(bridge)
    number = bridge.ship_bom({**draft, "review_id": plan["review_id"]})["data"]["shipment_number"]
    detail = bridge.shipment_detail(number)["data"]
    assert [(c["lot_number"], c["quantity"]) for c in detail["consumed_components"]] == [
        ("A", 5),
        ("B", 9),
    ]
    host.selection.write_text(f"{HEADER}\nKIT,SUB,5\nSUB,LEAF,7\nKIT,LEAF,4\n", encoding="utf-8")
    review = bridge.select_import("bom")["data"]
    assert commit(bridge, review)["ok"]

    assert links(bridge, "SUB") == {"LEAF": 7}
    assert bridge.shipment_detail(number)["data"] == detail
    assert (
        bridge.history_detail(detail["transactions"][1]["transaction_id"])["data"]["shipment"]
        == detail
    )
    # Imported definitions apply to later reviews only; stock stayed where it was.
    assert (stock(bridge, "KIT"), stock(bridge, "SUB"), stock(bridge, "LEAF")) == (10, 10, 21)
    assert context.backups.exists()


def test_a_reviewed_bom_shipment_cannot_confirm_after_the_definition_import_changes_it(tmp_path):
    _store, bridge, _context, host = stocked(tmp_path)
    draft, plan = bom_shipment(bridge)
    assert [(line["lot_number"], line["quantity_allocated"]) for line in plan["plan"]["lines"]] == [
        ("A", 5),
        ("B", 9),
    ]
    host.selection.write_text(f"{HEADER}\nKIT,LEAF,5\n", encoding="utf-8")
    review = bridge.select_import("bom")["data"]
    assert review["preview"]["warnings"]
    assert commit(bridge, review)["ok"]
    before = (stock(bridge, "LEAF"), len(records(bridge)))

    rejected = bridge.ship_bom({**draft, "review_id": plan["review_id"]})

    assert rejected["error"]["code"] == "PLAN_CHANGED"
    assert (stock(bridge, "LEAF"), len(records(bridge))) == before
    assert bridge.ship_bom({**draft, "review_id": plan["review_id"]})["ok"] is False
    fresh = bridge.preview_bom_ship(draft)["data"]
    assert [
        (line["lot_number"], line["quantity_allocated"]) for line in fresh["plan"]["lines"]
    ] == [
        ("A", 5),
        ("B", 17),
    ]
    shipped = bridge.ship_bom({**draft, "review_id": fresh["review_id"]})
    assert shipped["ok"]
    assert stock(bridge, "LEAF") == 13


def test_a_definition_import_that_leaves_the_reviewed_allocation_unchanged_still_ships_it(tmp_path):
    _store, bridge, _context, host = stocked(tmp_path)
    draft, plan = bom_shipment(bridge)
    # A new unrelated component of another assembly changes nothing this review consumes.
    host.selection.write_text(f"{HEADER}\nBOLT,LEAF,1\n", encoding="utf-8")
    assert commit(bridge, bridge.select_import("bom")["data"])["ok"]
    shipped = bridge.ship_bom({**draft, "review_id": plan["review_id"]})
    assert shipped["ok"]
    assert stock(bridge, "LEAF") == 21
