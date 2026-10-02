import json

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
    assert (
        bridge.history_detail(record["transaction_id"])["data"]["transaction"]["notes"]
        == ""
    )
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    assert (
        InventoryBridge(reopened).history_detail(record["transaction_id"])["data"][
            "transaction"
        ]
        == record
    )
    assert (
        InventoryBridge(reopened).shipment_detail(number)["data"]["recipient"]
        == "Customer"
    )
    reopened.engine.dispose()


def test_history_empty_unknown_and_invalid_reads_are_explicit(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    bridge = InventoryBridge(store)
    assert bridge.history({})["data"] == dict(
        records=[], types=[], total=0, matching=0, page=0
    )
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
    store.engine.dispose()


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
