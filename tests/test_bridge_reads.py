"""Desktop read contracts, query growth, and file-backed snapshot isolation."""

from contextlib import contextmanager

import pytest
from sqlalchemy import event, select

from inventory_control.bridge import InventoryBridge
from inventory_control.orm import LocationRecord
from inventory_control.store import InventoryStore


@pytest.fixture
def inventory(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    yield store, InventoryBridge(store)
    store.engine.dispose()


@contextmanager
def select_count(store):
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(store.engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(store.engine, "before_cursor_execute", record)


def desktop_read(bridge, name):
    if name == "search_parts":
        return bridge.search_parts({})
    if name == "dashboard":
        return bridge.dashboard()
    return getattr(bridge, name)("A")


@pytest.mark.parametrize("name", ["search_parts", "dashboard", "part_detail", "stock_context"])
def test_read_query_count_does_not_grow_with_unrelated_inventory(inventory, name):
    store, bridge = inventory
    store.add_part("A", "Selected part", minimum_quantity=5)
    store.receive("A", 5, "Stock", "A-LOT", "Pat")
    counts = []
    for start, end in ((0, 9), (9, 99)):
        for index in range(start, end):
            number = f"OTHER-{index:03}"
            store.add_part(number, "Unrelated part", minimum_quantity=2)
            store.receive(number, 2, "Stock", number, "Other")
            store.ship(number, 1, "Stock", "Customer", "Other", lot_number=number)
        with select_count(store) as queries:
            result = desktop_read(bridge, name)
        assert result["ok"], result
        counts.append(len(queries))
        if name == "stock_context":
            assert len(result["data"]["transactions"]) == 1
            assert result["data"]["shipments"] == []
    # Allow query reshaping, while rejecting a query per Part, lot, or shipment.
    assert counts[1] <= counts[0] + 2, counts
    assert counts[1] <= 12, counts


@pytest.mark.parametrize("name", ["search_parts", "dashboard", "part_detail", "stock_context"])
def test_read_holds_one_snapshot_while_another_store_commits(inventory, name):
    store, bridge = inventory
    store.add_part("A", "Selected part", minimum_quantity=5)
    store.receive("A", 5, "Stock", "A-LOT", "Pat")
    writer = InventoryStore(store.db_path, seed=False)
    before = desktop_read(bridge, name)
    assert before["ok"]
    wrote = False

    def commit_during_read(connection, cursor, statement, parameters, context, many):
        nonlocal wrote
        if wrote or not statement.lstrip().upper().startswith("SELECT"):
            return
        wrote = True
        writer.receive("A", 4, "Stock", "A-LOT", "Other")
        writer.ship("A", 1, "Stock", "Customer", "Other", lot_number="A-LOT")

    event.listen(store.engine, "after_cursor_execute", commit_during_read)
    try:
        during = desktop_read(bridge, name)
    finally:
        event.remove(store.engine, "after_cursor_execute", commit_during_read)
        writer.engine.dispose()
    assert wrote
    assert during == before
    # Closing the read releases its snapshot; the next request sees the commit.
    after = desktop_read(bridge, name)
    assert after["ok"]
    assert after != before
    assert bridge.part_detail("A")["data"]["quantity"] == 8


def test_catalog_preserves_unicode_matching_and_descending_ties(inventory):
    store, bridge = inventory
    store.add_part("A", "Straße", minimum_quantity=1)
    store.add_part("B", "STRASSE", minimum_quantity=1)
    store.add_part("C", "Other")
    result = bridge.search_parts({"query": "strasse", "sort": "description", "descending": True})
    assert result["ok"]
    assert [part["part_number"] for part in result["data"]] == ["B", "A"]
    assert all(part["low_stock"] for part in result["data"])
    assert [
        part["part_number"]
        for part in bridge.search_parts({"sort": "quantity", "descending": True})["data"]
    ] == ["C", "B", "A"]


def test_detail_preserves_inactive_location_stock_and_zero_lots(inventory):
    store, bridge = inventory
    store.add_part("A", "Selected part", minimum_quantity=5)
    store.receive("A", 2, "Receiving", "B", "Pat")
    store.receive("A", 1, "Stock", "EMPTY", "Pat")
    store.ship("A", 1, "Stock", "Customer", "Pat", lot_number="EMPTY")
    with store.session_factory.begin() as session:
        session.scalar(
            select(LocationRecord).where(LocationRecord.name == "Receiving")
        ).active = False
    result = bridge.stock_context(" a ")
    assert result["ok"]
    context = result["data"]
    assert context["locations"] == ["Stock", "Shipping Bench", "Scrap"]
    assert context["part"]["quantity"] == 2
    assert context["part"]["low_stock"] is True
    assert context["part"]["location_balances"] == {
        "Receiving": 2,
        "Stock": 0,
        "Shipping Bench": 0,
        "Scrap": 0,
    }
    assert context["part"]["balances"] == [
        dict(part_number="A", location="Receiving", lot_number="B", quantity=2),
        dict(part_number="A", location="Stock", lot_number="EMPTY", quantity=0),
    ]
    assert bridge.part_detail("A")["data"] == context["part"]


def test_context_keeps_complete_ordered_audit_without_per_record_queries(inventory):
    store, bridge = inventory
    store.add_part("A", "Selected part")
    numbers = []
    for index in range(55):
        lot = f"LOT-{index:03}"
        store.receive("A", 2, "Stock", lot, "Pat", reference=f"R-{index}")
        numbers.append(store.ship("A", 1, "Stock", "Customer", "Pat", lot_number=lot))
    with select_count(store) as queries:
        result = bridge.stock_context("A")
    assert result["ok"]
    context = result["data"]
    assert len(context["transactions"]) == 110
    assert [tx["lot_number"] for tx in context["transactions"]] == [
        f"LOT-{index:03}" for index in reversed(range(55)) for _ in range(2)
    ]
    assert [s["shipment_number"] for s in context["shipments"]] == numbers[::-1]
    assert all(s["consumed_components"] == [] for s in context["shipments"])
    assert set(context["transactions"][0]) == {
        "timestamp",
        "tx_type",
        "part_number",
        "quantity_change",
        "location_from",
        "location_to",
        "operator",
        "reference",
        "notes",
        "lot_number",
    }
    assert set(context["shipments"][0]) == {
        "shipment_number",
        "timestamp",
        "part_number",
        "quantity",
        "recipient",
        "carrier",
        "tracking_number",
        "consumed_components",
    }
    assert len(queries) <= 12


def test_context_returns_each_bom_shipment_once_with_persisted_consumption(inventory):
    store, bridge = inventory
    for part in ("KIT", "X", "Y"):
        store.add_part(part, part)
    store.add_bom_component("KIT", "X", 2)
    store.add_bom_component("KIT", "Y", 1)
    store.receive("X", 1, "Stock", "A", "Pat")
    store.receive("X", 5, "Stock", "B", "Pat")
    store.receive("Y", 4, "Stock", "C", "Pat")
    number = store.ship(
        "KIT",
        2,
        "Stock",
        "Customer",
        "Pat",
        expected_bom_plan=store.prepare_bom_shipment("KIT", 2, "Stock"),
    )
    store.remove_bom_component("KIT", "X")
    with select_count(store) as queries:
        result = bridge.stock_context("KIT")
    assert result["ok"]
    context = result["data"]
    assert context["has_bom"] is True
    assert context["part"]["quantity"] == 0
    assert len(context["shipments"]) == 1
    assert context["shipments"][0]["shipment_number"] == number
    assert context["shipments"][0]["consumed_components"] == [
        dict(part_number="X", quantity=1, location="Stock", lot_number="A"),
        dict(part_number="X", quantity=3, location="Stock", lot_number="B"),
        dict(part_number="Y", quantity=2, location="Stock", lot_number="C"),
    ]
    assert [tx["tx_type"] for tx in context["transactions"]] == ["SHIP_BOM"]
    assert len(queries) <= 12


def test_read_failure_releases_snapshot_and_returns_safe_error(inventory, caplog):
    store, bridge = inventory
    store.add_part("A", "Selected part")
    selects = 0

    def fail(connection, cursor, statement, parameters, context, executemany):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1
            if selects == 2:
                raise RuntimeError("Private read failure")

    event.listen(store.engine, "before_cursor_execute", fail)
    try:
        response = bridge.stock_context("A")
    finally:
        event.remove(store.engine, "before_cursor_execute", fail)
    assert response["error"]["code"] == "INTERNAL"
    assert "Private" not in response["error"]["message"]
    assert "Private read failure" in caplog.text
    store.receive("A", 1, "Stock", "NEW", "Pat")
    assert bridge.stock_context("A")["data"]["part"]["quantity"] == 1
