import json

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


def test_dashboard_reads_real_store(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    bridge = InventoryBridge(store)
    assert bridge.dashboard()["data"] == {
        "active_parts": 0,
        "low_stock": [],
        "shipment_count": 0,
        "activity": [],
    }
    store.add_part("A", "Bearing", minimum_quantity=5)
    store.receive("A", 3, "Stock", "L1", "Pat")
    result = bridge.dashboard()
    assert result["ok"] is True
    assert result["data"]["active_parts"] == 1
    assert result["data"]["low_stock"][0]["quantity"] == 3
    assert result["data"]["activity"][0]["operator"] == "Pat"
    json.dumps(result, allow_nan=False)


def test_preferences_validate_and_survive_restart(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)
    assert bridge.preferences()["data"] == {"operator": "", "theme": "light"}
    assert bridge.save_operator(" Pat ")["data"]["operator"] == "Pat"
    assert bridge.save_theme("dark")["ok"]
    assert bridge.save_operator(12)["error"]["code"] == "VALIDATION"
    assert bridge.save_theme("system")["error"]["code"] == "VALIDATION"
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    assert InventoryBridge(reopened).preferences()["data"] == {
        "operator": "Pat",
        "theme": "dark",
    }


def test_catalog_search_filters_sort_and_balances(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing", minimum_quantity=5)
    store.add_part("B", "Cable")
    store.add_part("C", "Old bearing", minimum_quantity=5)
    store.set_part_active("C", False)
    store.receive("A", 2, "Stock", "L1", "Pat")
    store.receive("A", 1, "Receiving", "L2", "Pat")
    bridge = InventoryBridge(store)
    assert [p["part_number"] for p in bridge.search_parts({"query": "bearing"})["data"]] == [
        "A",
        "C",
    ]
    assert [p["part_number"] for p in bridge.search_parts({"status": "inactive"})["data"]] == ["C"]
    assert [p["part_number"] for p in bridge.search_parts({"low_stock": True})["data"]] == ["A"]
    assert [
        p["part_number"]
        for p in bridge.search_parts({"sort": "part_number", "descending": True})["data"]
    ] == ["C", "B", "A"]
    detail = bridge.part_detail("a")["data"]
    assert detail["quantity"] == 3
    assert detail["low_stock"] is True
    assert detail["balances"] == [
        {
            "part_number": "A",
            "lot_number": "L2",
            "location": "Receiving",
            "quantity": 1,
        },
        {"part_number": "A", "lot_number": "L1", "location": "Stock", "quantity": 2},
    ]
    assert detail["location_balances"]["Stock"] == 2
    assert bridge.part_detail("missing")["error"]["code"] == "NOT_FOUND"
    assert bridge.search_parts({"sort": "unknown"})["error"]["code"] == "VALIDATION"


def test_creation_errors_and_restart(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)
    request = {
        "part_number": " a ",
        "description": "Bearing",
        "minimum_quantity": 3,
        "location": "Stock",
    }
    assert "Stock" in bridge.locations()["data"]
    created = bridge.create_part(request)
    assert created["ok"]
    assert created["data"]["part_number"] == "A"
    assert bridge.create_part(request)["error"] == {
        "code": "DUPLICATE",
        "message": "Part already exists.",
    }
    for invalid in (
        None,
        [],
        {**request, "minimum_quantity": True},
        {**request, "minimum_quantity": 1.5},
        {**request, "minimum_quantity": -1},
        {**request, "description": ""},
        {**request, "part_number": "B", "location": "unknown"},
        {**request, "active": False},
    ):
        assert bridge.create_part(invalid)["error"]["code"] == "VALIDATION"
    assert len(bridge.search_parts({})["data"]) == 1
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    assert InventoryBridge(reopened).part_detail("A")["data"]["minimum_quantity"] == 3


def test_unexpected_errors_are_safe_and_logged(tmp_path, monkeypatch, caplog):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    bridge = InventoryBridge(store)

    def fail(*args):
        raise RuntimeError("private technical detail")

    monkeypatch.setattr(store, "get_setting", fail)
    result = bridge.preferences()
    assert result["error"]["code"] == "INTERNAL"
    assert "private technical detail" not in json.dumps(result)
    assert "private technical detail" in caplog.text


def test_invalid_bridge_requests_do_not_change_catalog(tmp_path):
    bridge = InventoryBridge(InventoryStore(tmp_path / "inventory.db", seed=False))
    for request in (
        None,
        [],
        {"query": 3},
        {"status": []},
        {"sort": {}},
        {"low_stock": "yes"},
        {"descending": 1},
        {"sql": "SELECT 1"},
    ):
        assert bridge.search_parts(request)["error"]["code"] == "VALIDATION"
    for value in (None, [], {}, True, ""):
        assert bridge.part_detail(value)["error"]["code"] == "VALIDATION"
    for value in (None, [], {}, True):
        assert bridge.save_operator(value)["error"]["code"] == "VALIDATION"
        assert bridge.save_theme(value)["error"]["code"] == "VALIDATION"
    assert bridge.search_parts({})["data"] == []


def test_catalog_reports_activity_and_stock_state_separately(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Threshold", minimum_quantity=3)
    store.add_part("B", "No minimum")
    store.receive("A", 3, "Stock", "L1", "Pat")
    bridge = InventoryBridge(store)
    assert bridge.part_detail("A")["data"]["low_stock"] is True
    assert bridge.part_detail("B")["data"]["low_stock"] is False
    store.set_part_active("A", False)
    part = bridge.part_detail("A")["data"]
    assert part["active"] is False
    assert part["low_stock"] is False
    assert part["quantity"] == 3
    assert bridge.dashboard()["data"]["low_stock"] == []
