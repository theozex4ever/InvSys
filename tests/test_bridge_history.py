import json

from inventory_control.acceptance import create_fixture
from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


def test_history_links_standard_shipment_even_with_custom_reference_after_reopen(
    tmp_path,
):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    store.add_part("A", "Bearing")
    store.receive("A", 10, "Stock", "LOT-A", "Pat", notes="Checked")
    bridge = InventoryBridge(store)
    number = bridge.ship(
        dict(
            part_number="A",
            quantity=3,
            location="Stock",
            lot_number="LOT-A",
            operator="Pat",
            recipient="Customer",
            reference="ORDER-9",
        )
    )["data"]["shipment_number"]
    for query in ("a", "lot-a", "pat", number.lower(), "order-9"):
        records = bridge.history(dict(query=query, tx_type="SHIP"))["data"]["records"]
        assert len(records) == 1
        assert records[0]["shipment_number"] == number
    record = records[0]
    detail = bridge.history_detail(record["transaction_id"])["data"]
    assert detail["transaction"]["quantity_change"] == -3
    assert detail["transaction"]["reference"] == "ORDER-9"
    assert detail["shipment"]["recipient"] == "Customer"
    assert detail["shipment"]["consumed_components"] == []
    assert bridge.shipment_detail(number)["data"]["transactions"] == [record]
    assert bridge.dashboard()["data"]["activity"][0] == record
    json.dumps(detail)
    # Mutating a response never changes the audit trail.
    detail["transaction"]["notes"] = "Changed"
    assert bridge.history_detail(record["transaction_id"])["data"]["transaction"]["notes"] == ""
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    assert (
        InventoryBridge(reopened).history_detail(record["transaction_id"])["data"]["transaction"]
        == record
    )
    assert InventoryBridge(reopened).shipment_detail(number)["data"]["recipient"] == "Customer"
    reopened.engine.dispose()


def test_history_empty_unknown_and_invalid_reads_are_explicit(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    bridge = InventoryBridge(store)
    assert bridge.history({})["data"] == dict(records=[], types=[], total=0, matching=0, page=0)
    assert bridge.history_detail(999)["error"]["code"] == "NOT_FOUND"
    assert bridge.shipment_detail("missing")["error"]["code"] == "NOT_FOUND"
    for invalid in (None, [], {"query": True}, {"tx_type": []}, {"sql": "SELECT 1"}):
        assert bridge.history(invalid)["error"]["code"] == "VALIDATION"
    for invalid in (None, True, "1", 1.5, 0, -1):
        assert bridge.history_detail(invalid)["error"]["code"] == "VALIDATION"
    store.add_part("A", "Bearing")
    store.receive("A", 2, "Stock", "L", "Pat", notes="Checked")
    assert bridge.history({"query": "missing"})["data"]["records"] == []
    tx = bridge.history({})["data"]["records"][0]
    detail = bridge.history_detail(tx["transaction_id"])["data"]
    assert detail["shipment"] is None
    assert detail["transaction"]["notes"] == "Checked"
    store.engine.dispose()


def test_history_pages_are_bounded_without_hiding_older_matches(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing")
    for index in range(55):
        store.receive("A", 1, "Stock", f"L-{index}", "Pat")
    bridge = InventoryBridge(store)
    first = bridge.history({})["data"]
    assert len(first["records"]) == 50
    assert first["matching"] == 55
    second = bridge.history({"page": 1})["data"]
    assert len(second["records"]) == 5
    assert not {r["transaction_id"] for r in first["records"]} & {
        r["transaction_id"] for r in second["records"]
    }
    assert bridge.history({"query": "L-0"})["data"]["records"][0]["lot_number"] == "L-0"
    for page in (-1, True, "1", 1.2):
        assert bridge.history({"page": page})["error"]["code"] == "VALIDATION"
    # Sorting happens before paging, so pages partition the sorted matches.
    ascending = [
        record["lot_number"]
        for page in (0, 1)
        for record in bridge.history({"sort": "lot_number", "descending": False, "page": page})[
            "data"
        ]["records"]
    ]
    assert ascending == sorted(f"L-{index}" for index in range(55))
    for invalid in ({"sort": "id"}, {"sort": None}, {"descending": "yes"}, {"descending": 0}):
        assert bridge.history(invalid)["error"]["code"] == "VALIDATION"
    store.engine.dispose()


def test_history_text_search_covers_every_original_column(tmp_path):
    """A16: Notes, both Locations, timestamp and type text, alongside the exact-type filter."""
    path = create_fixture(tmp_path / "acceptance")
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)

    def matches(**search):
        return bridge.history(search)["data"]["records"]

    assert len(matches()) == 15
    date = matches()[0]["timestamp"][:10]
    assert len(matches(query="Disposable baseline")) == 8
    assert len(matches(query="dISPOSABLE BASELINE")) == 8
    assert {r["tx_type"] for r in matches(query="Shipping Bench")} == {"MOVE_OUT", "MOVE_IN"}
    assert {r["tx_type"] for r in matches(query="move_")} == {"MOVE_OUT", "MOVE_IN"}
    assert [r["tx_type"] for r in matches(query="MOVE_", tx_type="MOVE_IN")] == ["MOVE_IN"]
    assert len(matches(query=date)) == 15
    assert [r["part_number"] for r in matches(query="used by kit")] == ["LEAF", "LEAF"]
    # A later transfer out of Shipping Bench matches by source; Scrap only by destination.
    store.move("STANDARD", 1, "Shipping Bench", "Scrap", "B", "Pat")
    assert len(matches(query="Shipping Bench")) == 4
    assert {(r["location_from"], r["location_to"]) for r in matches(query="scrap")} == {
        ("Shipping Bench", "Scrap")
    }
    # Existing Part, Lot, operator, reference and shipment searches keep working.
    assert len(matches(query="INTERMEDIATE")) == 1
    assert len(matches(query="ACCEPT-STANDARD")) == 1
    assert len(matches(query="Pat")) == 2
    assert len(matches()) == 17
    store.engine.dispose()


def test_history_sorts_every_original_column_without_changing_records(tmp_path):
    """A17: ascending and descending sort on all nine columns, signed Qty numerically."""
    path = create_fixture(tmp_path / "acceptance")
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)
    before = bridge.history({})["data"]
    for sort in InventoryStore.HISTORY_SORTS:
        for descending in (False, True):
            result = bridge.history({"sort": sort, "descending": descending})["data"]
            keys = [(r[sort], r["transaction_id"]) for r in result["records"]]
            assert keys == sorted(keys, reverse=descending), (sort, descending)
            assert result["matching"] == 15
            assert sorted(map(json.dumps, result["records"])) == sorted(
                map(json.dumps, before["records"])
            )
    quantities = bridge.history({"sort": "quantity_change", "descending": False})["data"]
    assert quantities["records"][0]["quantity_change"] == -9
    newest = bridge.history({"sort": "quantity_change"})["data"]["records"][0]
    assert newest["quantity_change"] == 30
    # The default order stays newest first, and sorting combines with filters.
    assert bridge.history({})["data"]["records"][0]["tx_type"] == "SHIP_BOM"
    assert [
        r["quantity_change"]
        for r in bridge.history(
            {
                "query": "LEAF",
                "tx_type": "BOM_CONSUME",
                "sort": "quantity_change",
                "descending": False,
            }
        )["data"]["records"]
    ] == [-9, -5]
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    assert InventoryBridge(reopened).history({})["data"] == before
    reopened.engine.dispose()


def test_history_search_treats_wildcards_as_literal_text(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing")
    store.receive("A", 1, "Stock", "L", "Pat", reference="PO_100%")
    store.receive("A", 1, "Stock", "L", "Pat", reference="POx100y")
    records = InventoryBridge(store).history({"query": "po_100%"})["data"]["records"]
    assert len(records) == 1
    assert records[0]["reference"] == "PO_100%"
    store.engine.dispose()


def test_database_read_failures_are_safe_and_logged(tmp_path, caplog):
    from sqlalchemy import event

    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    bridge = InventoryBridge(store)

    def fail_read(*args):
        raise RuntimeError("Private database failure")

    event.listen(store.engine, "before_cursor_execute", fail_read)
    for response in (
        bridge.history({}),
        bridge.history_detail(1),
        bridge.shipment_detail("SHP-UNKNOWN"),
    ):
        assert response["error"]["code"] == "INTERNAL"
        assert "Private" not in response["error"]["message"]
    assert "Private database failure" in caplog.text
    event.remove(store.engine, "before_cursor_execute", fail_read)
    assert bridge.history({})["data"]["total"] == 0
    store.engine.dispose()
