"""Complete shipment reviews through the desktop bridge and real SQLite."""

import pytest
from sqlalchemy import event, select

from inventory_control.bridge import InventoryBridge
from inventory_control.orm import LocationRecord, LotRecord
from inventory_control.store import InventoryStore


@pytest.fixture
def reviews(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    for number in ("A", "KIT", "SUB", "LEAF"):
        store.add_part(number, number)
    store.receive("A", 7, "Stock", "L1", "Setup")
    store.receive("A", 20, "Stock", "L2", "Setup")
    store.add_bom_component("KIT", "SUB", 2)
    store.add_bom_component("SUB", "LEAF", 3)
    store.add_bom_component("KIT", "LEAF", 1)
    store.receive("LEAF", 5, "Stock", "A", "Setup")
    store.receive("LEAF", 15, "Stock", "B", "Setup")
    yield store, InventoryBridge(store)
    store.engine.dispose()


def draft(operation):
    fields = dict(
        part_number="A" if operation == "preview_ship" else "KIT",
        quantity=3 if operation == "preview_ship" else 2,
        location="Stock",
        operator="Pat",
        recipient="Customer",
    )
    if operation == "preview_ship":
        fields["lot_number"] = "L1"
    return fields


def review_data(response):
    assert response["ok"], response
    # Each ready BOM preview issues a new opaque capability.
    return {key: value for key, value in response["data"].items() if key != "review_id"}


@pytest.mark.parametrize("operation", ["preview_ship", "preview_bom_ship"])
@pytest.mark.parametrize("write_at", ["first", "middle", "last"])
def test_review_holds_one_snapshot_across_validation_and_stock_reads(reviews, operation, write_at):
    store, bridge = reviews
    request = draft(operation)
    preview = getattr(bridge, operation)
    queries = []

    def record_query(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(store.engine, "after_cursor_execute", record_query)
    try:
        before = review_data(preview(request))
    finally:
        event.remove(store.engine, "after_cursor_execute", record_query)
    write_after = {
        "first": 1,
        "middle": max(1, len(queries) // 2),
        "last": len(queries),
    }[write_at]
    writer = InventoryStore(store.db_path, seed=False)
    selects = 0
    wrote = False

    def commit_during_read(connection, cursor, statement, parameters, context, many):
        nonlocal selects, wrote
        if not statement.lstrip().upper().startswith("SELECT"):
            return
        selects += 1
        if selects == write_after:
            part, lot = ("A", "L1") if operation == "preview_ship" else ("LEAF", "A")
            writer.ship(part, 2, "Stock", "Other customer", "Other", lot_number=lot)
            wrote = True

    event.listen(store.engine, "after_cursor_execute", commit_during_read)
    try:
        during = review_data(preview(request))
    finally:
        event.remove(store.engine, "after_cursor_execute", commit_during_read)
        writer.engine.dispose()
    assert wrote
    assert during == before
    after = review_data(preview(request))
    assert after != before
    if operation == "preview_ship":
        assert (after["lot_stock"], after["location_stock"], after["remaining"]) == (
            5,
            25,
            2,
        )
    else:
        assert after["plan"]["requirements"][0]["stock_available"] == 18
        assert [line["quantity_allocated"] for line in after["plan"]["lines"]] == [
            3,
            11,
        ]


@pytest.mark.parametrize("operation", ["preview_ship", "preview_bom_ship"])
def test_review_part_eligibility_uses_the_same_snapshot(reviews, operation):
    store, bridge = reviews
    request = draft(operation)
    preview = getattr(bridge, operation)
    before = review_data(preview(request))
    writer = InventoryStore(store.db_path, seed=False)
    wrote = False

    def deactivate_during_read(connection, cursor, statement, parameters, context, many):
        nonlocal wrote
        if not wrote and statement.lstrip().upper().startswith("SELECT"):
            writer.set_part_active(request["part_number"], False)
            wrote = True

    event.listen(store.engine, "after_cursor_execute", deactivate_during_read)
    try:
        assert review_data(preview(request)) == before
    finally:
        event.remove(store.engine, "after_cursor_execute", deactivate_during_read)
        writer.engine.dispose()
    assert wrote
    assert preview(request)["error"]["code"] == "VALIDATION"


def test_review_preserves_distinct_inactive_location_rules(reviews):
    store, bridge = reviews
    with store.session_factory.begin() as session:
        session.scalar(select(LocationRecord).where(LocationRecord.name == "Stock")).active = False
    standard = bridge.preview_ship(draft("preview_ship"))
    assert standard["error"] == {"code": "VALIDATION", "message": "Invalid location."}
    bom = bridge.preview_bom_ship(draft("preview_bom_ship"))
    assert bom["ok"]
    assert bom["data"]["plan"]["ready"]
    assert "Stock" not in bom["data"]["context"]["locations"]


def test_standard_review_distinguishes_missing_lots_from_zero_local_stock(reviews):
    store, bridge = reviews
    request = draft("preview_ship")
    missing = bridge.preview_ship({**request, "lot_number": "MISSING"})
    assert missing["error"] == {"code": "NOT_FOUND", "message": "Lot not found."}
    empty = bridge.preview_ship({**request, "location": "Receiving"})
    assert empty["error"] == {
        "code": "VALIDATION",
        "message": "Not enough stock in selected lot. Available: 0, requested: 3.",
    }
    with store.session_factory.begin() as session:
        session.scalar(select(LotRecord).where(LotRecord.lot_number == "L1")).active = False
    assert bridge.preview_ship(request)["ok"]


@pytest.mark.parametrize("operation", ["preview_ship", "preview_bom_ship"])
def test_missing_review_part_keeps_not_found_response(reviews, operation):
    _, bridge = reviews
    response = getattr(bridge, operation)({**draft(operation), "part_number": "MISSING"})
    assert response["error"] == {"code": "NOT_FOUND", "message": "Part not found."}
