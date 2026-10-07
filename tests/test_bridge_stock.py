import json

import pytest

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


def test_receipt_records_lot_stock_and_audit_after_restart(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    store.add_part("A", "Bearing", location="Receiving")
    bridge = InventoryBridge(store)
    result = bridge.receive(
        {
            "part_number": " a ",
            "quantity": 7,
            "location": "Receiving",
            "lot_number": " lot-1 ",
            "operator": " Pat ",
            "reference": " PO-12 ",
            "notes": " Checked ",
        }
    )
    assert result["ok"]
    assert result["data"]["part"]["quantity"] == 7
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    context = InventoryBridge(reopened).stock_context("A")["data"]
    assert context["part"]["balances"] == [
        {
            "part_number": "A",
            "location": "Receiving",
            "lot_number": "LOT-1",
            "quantity": 7,
        }
    ]
    tx = context["transactions"][0]
    assert (
        tx["tx_type"],
        tx["quantity_change"],
        tx["lot_number"],
        tx["location_to"],
        tx["operator"],
        tx["reference"],
        tx["notes"],
    ) == (
        "RECEIVE",
        7,
        "LOT-1",
        "Receiving",
        "Pat",
        "PO-12",
        "Checked",
    )
    assert context["shipments"] == []
    reopened.engine.dispose()


@pytest.mark.parametrize("operation", ["receive", "preview_ship", "ship"])
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        {"quantity": True},
        {"quantity": 1.5},
        {"quantity": "1"},
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": 2**31},
        {"part_number": "missing"},
        {"part_number": 12},
        {"part_number": ""},
        {"location": "missing"},
        {"location": []},
        {"lot_number": ""},
        {"lot_number": None},
        {"operator": " "},
        {"operator": 12},
        {"reference": []},
        {"sql": "SELECT 1"},
    ],
)
def test_invalid_stock_requests_have_no_effects(tmp_path, operation, invalid):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing")
    store.receive("A", 10, "Stock", "L1", "Pat")
    bridge = InventoryBridge(store)
    before = bridge.stock_context("A")
    request = {
        "part_number": "A",
        "quantity": 1,
        "location": "Stock",
        "lot_number": "L1",
        "operator": "Pat",
    }
    if operation != "receive":
        request["recipient"] = "Customer"
    result = getattr(bridge, operation)(
        {**request, **invalid} if isinstance(invalid, dict) else invalid
    )
    assert result["ok"] is False
    assert result["error"]["code"] in ("VALIDATION", "NOT_FOUND")
    assert bridge.stock_context("A") == before
    store.engine.dispose()


@pytest.mark.parametrize(
    "invalid",
    [
        {"recipient": " "},
        {"recipient": False},
        {"lot_number": "missing"},
        {"quantity": 4},
        {"carrier": 12},
        {"tracking": []},
        {"notes": "unsupported"},
    ],
)
def test_ship_rejections_preserve_stock_and_records(tmp_path, invalid):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing")
    store.receive("A", 3, "Stock", "L1", "Pat")
    store.receive("A", 20, "Stock", "L2", "Pat")
    bridge = InventoryBridge(store)
    request = {
        "part_number": "A",
        "quantity": 1,
        "location": "Stock",
        "lot_number": "L1",
        "operator": "Pat",
        "recipient": "Customer",
        **invalid,
    }
    before = bridge.stock_context("A")
    assert bridge.preview_ship(request)["ok"] is False
    assert bridge.ship(request)["ok"] is False
    assert bridge.stock_context("A") == before
    store.engine.dispose()


def test_shipment_revalidates_after_review_and_blocks_bom_and_inactive_parts(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing")
    store.add_part("KIT", "Kit")
    store.add_bom_component("KIT", "A", 1)
    store.receive("A", 5, "Stock", "L1", "Pat")
    store.receive("KIT", 10, "Stock", "K1", "Pat")
    bridge = InventoryBridge(store)
    request = {
        "part_number": "A",
        "quantity": 5,
        "location": "Stock",
        "lot_number": "L1",
        "operator": "Pat",
        "recipient": "Customer",
    }
    assert bridge.preview_ship(request)["ok"]
    assert bridge.ship({**request, "quantity": 1})["ok"]
    before = bridge.stock_context("A")
    assert bridge.ship(request)["ok"] is False
    assert bridge.stock_context("A") == before
    request.update(part_number="KIT", lot_number="K1", quantity=1)
    assert bridge.stock_context("KIT")["data"]["has_bom"] is True
    before = bridge.stock_context("KIT")
    assert "BOM" in bridge.preview_ship(request)["error"]["message"]
    assert "BOM" in bridge.ship(request)["error"]["message"]
    assert bridge.stock_context("KIT") == before
    store.set_part_active("A", False)
    before = bridge.stock_context("A")
    request.update(part_number="A", lot_number="L1")
    assert bridge.ship(request)["ok"] is False
    assert bridge.receive({k: v for k, v in request.items() if k != "recipient"})["ok"] is False
    assert bridge.stock_context("A") == before
    store.engine.dispose()


def test_standard_shipment_review_and_durable_audit(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    store.add_part("A", "Bearing")
    store.receive("A", 7, "Stock", "L1", "Pat")
    store.receive("A", 20, "Stock", "L2", "Pat")
    bridge = InventoryBridge(store)
    request = {
        "part_number": "a",
        "quantity": 3,
        "location": "Stock",
        "lot_number": "l1",
        "operator": " Pat ",
        "recipient": " Customer ",
        "carrier": " Courier ",
        "tracking": " TRACK-1 ",
        "reference": " ORDER-1 ",
    }
    preview = bridge.preview_ship(request)
    assert preview["ok"]
    assert preview["data"]["lot_stock"] == 7
    assert preview["data"]["location_stock"] == 27
    assert preview["data"]["remaining"] == 4
    assert len(bridge.stock_context("A")["data"]["transactions"]) == 2
    result = bridge.ship(request)
    assert result["ok"]
    number = result["data"]["shipment_number"]
    assert number.endswith("-0001")
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    bridge = InventoryBridge(reopened)
    context = bridge.stock_context("A")["data"]
    assert context["part"]["quantity"] == 24
    tx = context["transactions"][0]
    assert (
        tx["tx_type"],
        tx["quantity_change"],
        tx["lot_number"],
        tx["location_from"],
        tx["operator"],
        tx["reference"],
        tx["notes"],
    ) == (
        "SHIP",
        -3,
        "L1",
        "Stock",
        "Pat",
        "ORDER-1",
        "",
    )
    shipment = context["shipments"][0]
    assert (
        shipment["shipment_number"],
        shipment["quantity"],
        shipment["recipient"],
        shipment["carrier"],
        shipment["tracking_number"],
    ) == (
        number,
        3,
        "Customer",
        "Courier",
        "TRACK-1",
    )
    result = bridge.ship({**request, "reference": ""})
    assert result["data"]["shipment_number"].endswith("-0002")
    assert (
        bridge.stock_context("A")["data"]["transactions"][0]["reference"]
        == result["data"]["shipment_number"]
    )
    json.dumps(result, allow_nan=False)
    reopened.engine.dispose()
