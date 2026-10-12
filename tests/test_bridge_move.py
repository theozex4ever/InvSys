"""Move a Lot between Locations through the desktop bridge and real SQLite."""

import pytest
from sqlalchemy import event

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


@pytest.fixture
def moves(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    store.add_part("A", "Bearing", location="Stock")
    store.receive("A", 6, "Stock", "L1", "Setup")
    store.receive("A", 9, "Stock", "L2", "Setup")
    store.receive("A", 2, "Shipping Bench", "L1", "Setup")
    store.add_part("OTHER", "Other")
    yield path, store, InventoryBridge(store)
    store.engine.dispose()


def request(**changes):
    return {
        "part_number": "A",
        "quantity": 2,
        "location": "Stock",
        "destination": "Shipping Bench",
        "lot_number": "L1",
        "operator": "Pat",
        "reference": "REL-7",
        **changes,
    }


def lot_quantity(context, location, lot):
    return next(
        b["quantity"]
        for b in context["part"]["balances"]
        if b["location"] == location and b["lot_number"] == lot
    )


def test_review_reports_authoritative_before_and_after_for_both_locations(moves):
    _, _, bridge = moves
    review = bridge.preview_move(request(part_number=" a ", lot_number=" l1 "))
    assert review["ok"], review
    data = review["data"]
    assert data["request"]["part_number"] == "A"
    assert data["request"]["lot_number"] == "L1"
    assert (data["source_lot_before"], data["source_lot_after"]) == (6, 4)
    assert (data["destination_lot_before"], data["destination_lot_after"]) == (2, 4)
    assert (data["source_location_before"], data["source_location_after"]) == (15, 13)
    assert (data["destination_location_before"], data["destination_location_after"]) == (2, 4)
    assert data["context"]["part"]["part_number"] == "A"


def test_review_writes_nothing(moves):
    _, _, bridge = moves
    before = bridge.stock_context("A")
    assert bridge.preview_move(request())["ok"]
    assert bridge.stock_context("A") == before


def test_move_creates_paired_records_and_persists_after_restart(moves):
    path, store, bridge = moves
    result = bridge.move(request())
    assert result["ok"], result
    context = result["data"]
    assert lot_quantity(context, "Stock", "L1") == 4
    assert lot_quantity(context, "Shipping Bench", "L1") == 4
    assert lot_quantity(context, "Stock", "L2") == 9
    assert context["part"]["quantity"] == 17
    paired = context["transactions"][:2]
    assert [tx["tx_type"] for tx in paired] == ["MOVE_IN", "MOVE_OUT"]
    assert [tx["quantity_change"] for tx in paired] == [2, -2]
    for tx in paired:
        assert (tx["lot_number"], tx["operator"], tx["reference"]) == ("L1", "Pat", "REL-7")
        assert (tx["location_from"], tx["location_to"]) == ("Stock", "Shipping Bench")
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    persisted = InventoryBridge(reopened).stock_context("A")["data"]
    assert lot_quantity(persisted, "Stock", "L1") == 4
    assert lot_quantity(persisted, "Shipping Bench", "L1") == 4
    assert persisted["transactions"][:2] == paired
    reopened.engine.dispose()


def test_move_to_new_location_lot_creates_destination_balance(moves):
    _, _, bridge = moves
    result = bridge.move(request(lot_number="L2", destination="Scrap", quantity=9))
    assert result["ok"], result
    assert lot_quantity(result["data"], "Stock", "L2") == 0
    assert lot_quantity(result["data"], "Scrap", "L2") == 9


@pytest.mark.parametrize("operation", ["preview_move", "move"])
@pytest.mark.parametrize(
    "invalid,message",
    [
        ({"destination": "Stock"}, "Source and destination cannot match."),
        ({"destination": "Nowhere"}, "Invalid destination location."),
        ({"destination": ""}, "Destination required."),
        ({"destination": 3}, "Destination must be text."),
        ({"location": "Nowhere"}, "Invalid location."),
        ({"quantity": 7}, "Not enough stock"),
        ({"lot_number": "L3"}, "Lot not found"),
        ({"lot_number": ""}, "Lot required."),
        ({"quantity": 0}, "Quantity must be a whole number"),
        ({"quantity": True}, "Quantity must be a whole number"),
        ({"quantity": "2"}, "Quantity must be a whole number"),
        ({"operator": " "}, "Operator required."),
        ({"reference": []}, "Reference must be text."),
        ({"notes": "unsupported"}, "Invalid request fields."),
        ({"recipient": "Customer"}, "Invalid request fields."),
    ],
)
def test_rejected_moves_report_readable_errors_and_change_nothing(
    moves, operation, invalid, message
):
    _, _, bridge = moves
    before = bridge.stock_context("A")
    result = getattr(bridge, operation)(request(**invalid))
    assert result["ok"] is False
    assert result["error"]["code"] in ("VALIDATION", "NOT_FOUND")
    assert message in result["error"]["message"]
    assert bridge.stock_context("A") == before


@pytest.mark.parametrize("operation", ["preview_move", "move"])
def test_non_object_requests_are_rejected(moves, operation):
    _, _, bridge = moves
    before = bridge.stock_context("A")
    for invalid in (None, [], "A", 7):
        assert getattr(bridge, operation)(invalid)["ok"] is False
    assert bridge.stock_context("A") == before


@pytest.mark.parametrize("operation", ["preview_move", "move"])
def test_unknown_and_inactive_parts_are_rejected(moves, operation):
    _, store, bridge = moves
    missing = getattr(bridge, operation)(request(part_number="MISSING"))
    assert missing["ok"] is False
    assert missing["error"]["code"] == "NOT_FOUND"
    store.set_part_active("A", False)
    before = bridge.stock_context("A")
    inactive = getattr(bridge, operation)(request())
    assert inactive["ok"] is False
    assert "inactive" in inactive["error"]["message"].lower()
    assert bridge.stock_context("A") == before


def test_stale_review_cannot_overdraw_and_failure_is_atomic(moves):
    _, _, bridge = moves
    review = bridge.preview_move(request(quantity=5))
    assert review["ok"]
    # Another operator moves stock after the review was read.
    assert bridge.move(request(quantity=4))["ok"]
    before = bridge.stock_context("A")
    stale = bridge.move(review["data"]["request"])
    assert stale["ok"] is False
    assert stale["error"]["code"] == "VALIDATION"
    assert "Not enough stock" in stale["error"]["message"]
    assert bridge.stock_context("A") == before
    refreshed = bridge.preview_move(request(quantity=5))
    assert refreshed["ok"] is False


def test_write_failure_leaves_neither_movement_row_nor_balance_change(moves):
    _, store, bridge = moves
    before = bridge.stock_context("A")
    inserted = []

    def fail_second_row(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("INSERT INTO INVENTORY_TRANSACTIONS"):
            inserted.append(statement)
            if len(inserted) == 2:
                raise RuntimeError("disk failure")

    event.listen(store.engine, "before_cursor_execute", fail_second_row)
    try:
        result = bridge.move(request())
    finally:
        event.remove(store.engine, "before_cursor_execute", fail_second_row)
    assert inserted, "the test must intercept the transaction inserts"
    assert result["ok"] is False
    assert result["error"]["code"] == "INTERNAL"
    assert "disk failure" not in result["error"]["message"]
    assert bridge.stock_context("A") == before


def test_review_reads_one_snapshot_when_stock_changes_between_reads(moves):
    _, store, bridge = moves
    seen = []

    def record_query(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT") and not seen:
            seen.append(statement)
            # A concurrent writer commits after the review began reading.
            store.receive("A", 100, "Stock", "L1", "Other operator")

    event.listen(store.engine, "after_cursor_execute", record_query)
    try:
        data = bridge.preview_move(request())["data"]
    finally:
        event.remove(store.engine, "after_cursor_execute", record_query)
    assert seen
    assert data["source_lot_before"] == lot_quantity(data["context"], "Stock", "L1")
    assert data["source_location_before"] == data["context"]["part"]["location_balances"]["Stock"]


def test_acceptance_scenario_a07_moves_lot_b_and_survives_restart(tmp_path):
    from inventory_control.acceptance import create_fixture

    path = create_fixture(tmp_path / "acceptance")
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)
    draft = request(part_number="STANDARD", lot_number="B", operator="Acceptance operator")
    review = bridge.preview_move(draft)["data"]
    assert (review["source_lot_before"], review["source_lot_after"]) == (6, 4)
    assert (review["destination_lot_before"], review["destination_lot_after"]) == (2, 4)
    for rejected in (
        request(part_number="STANDARD", lot_number="B", destination="Stock"),
        request(part_number="STANDARD", lot_number="B", quantity=7),
    ):
        assert bridge.move(rejected)["ok"] is False
    before = bridge.stock_context("STANDARD")["data"]["transactions"]
    assert bridge.move(draft)["ok"]
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    context = InventoryBridge(reopened).stock_context("STANDARD")["data"]
    assert lot_quantity(context, "Stock", "B") == 4
    assert lot_quantity(context, "Shipping Bench", "B") == 4
    assert len(context["transactions"]) == len(before) + 2
    assert [t["reference"] for t in context["transactions"][:2]] == ["REL-7", "REL-7"]
    reopened.engine.dispose()
