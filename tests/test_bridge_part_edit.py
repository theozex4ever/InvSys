import json

import pytest

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


@pytest.fixture
def store(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing", minimum_quantity=5)
    store.add_part("B", "Cable")
    store.receive("A", 3, "Stock", "L1", "Pat")
    return store


def edit(**changes):
    return {
        "part_number": "A",
        "description": "Bearing assembly",
        "minimum_quantity": 8,
        "location": "Receiving",
    } | changes


def test_edit_persists_catalog_fields_and_keeps_identity_stock_and_history(store):
    bridge = InventoryBridge(store)
    before = store.history_records()
    result = bridge.update_part(edit(part_number=" a "))
    assert result["ok"] is True
    detail = result["data"]
    assert detail["part_number"] == "A"
    assert detail["description"] == "Bearing assembly"
    assert detail["minimum_quantity"] == 8
    assert detail["location"] == "Receiving"
    assert detail["active"] is True
    assert detail["quantity"] == 3
    assert [b["lot_number"] for b in detail["balances"]] == ["L1"]
    assert store.history_records() == before
    json.dumps(result, allow_nan=False)
    # The next reads reflect the edit: low-stock now uses the new minimum.
    assert bridge.search_parts({"query": "assembly"})["data"][0]["minimum_quantity"] == 8
    assert bridge.dashboard()["data"]["low_stock"][0]["minimum_quantity"] == 8


def test_edit_survives_restart(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    store.add_part("A", "Bearing")
    assert InventoryBridge(store).update_part(edit())["ok"]
    store.engine.dispose()
    reopened = InventoryBridge(InventoryStore(path, seed=False)).part_detail("A")["data"]
    assert (reopened["description"], reopened["minimum_quantity"], reopened["location"]) == (
        "Bearing assembly",
        8,
        "Receiving",
    )


def test_edit_preserves_inactive_state(store):
    store.set_part_active("B", False)
    bridge = InventoryBridge(store)
    assert bridge.update_part(edit(part_number="B", description="Cable v2"))["ok"]
    assert store.parts["B"].active is False
    assert store.parts["B"].description == "Cable v2"


def test_invalid_edits_are_rejected_without_changing_the_part(store):
    bridge = InventoryBridge(store)
    original = bridge.part_detail("A")["data"]
    for invalid in (
        None,
        [],
        edit(description=""),
        edit(description="   "),
        edit(description=5),
        edit(minimum_quantity=True),
        edit(minimum_quantity=1.5),
        edit(minimum_quantity=-1),
        edit(minimum_quantity=2**31),
        edit(location="unknown"),
        edit(location=None),
        edit(active=False),
        edit(new_part_number="Z"),
        {k: v for k, v in edit().items() if k != "description"},
    ):
        assert bridge.update_part(invalid)["error"]["code"] == "VALIDATION", invalid
    assert bridge.update_part(edit(part_number="missing"))["error"]["code"] == "NOT_FOUND"
    assert bridge.update_part(edit(part_number=""))["error"]["code"] == "VALIDATION"
    assert bridge.part_detail("A")["data"] == original
    assert "MISSING" not in store.parts


def test_deactivate_stocked_part_requires_confirmation(store):
    bridge = InventoryBridge(store)
    refused = bridge.set_part_active({"part_number": "A", "active": False})
    assert refused["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert "3" in refused["error"]["message"]
    assert store.parts["A"].active is True
    explicit_no = bridge.set_part_active(
        {"part_number": "A", "active": False, "confirm_stock": False}
    )
    assert explicit_no["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert store.parts["A"].active is True


def test_deactivate_and_reactivate_keep_stock_history_and_lots(store):
    bridge = InventoryBridge(store)
    history = store.history_records()
    deactivated = bridge.set_part_active(
        {"part_number": "a", "active": False, "confirm_stock": True}
    )
    assert deactivated["ok"] is True
    assert deactivated["data"]["active"] is False
    assert deactivated["data"]["quantity"] == 3
    assert deactivated["data"]["low_stock"] is False
    # Existing eligibility rules: inactive Parts cannot take new activity.
    assert (
        "inactive"
        in bridge.receive(
            {
                "part_number": "A",
                "quantity": 1,
                "location": "Stock",
                "lot_number": "L2",
                "operator": "Pat",
            }
        )["error"]["message"]
    )
    assert [p["part_number"] for p in bridge.search_parts({"status": "inactive"})["data"]] == ["A"]
    assert bridge.dashboard()["data"]["low_stock"] == []
    reactivated = bridge.set_part_active({"part_number": "A", "active": True})
    assert reactivated["data"]["active"] is True
    assert reactivated["data"]["low_stock"] is True
    assert store.history_records() == history
    assert store.parts["A"].description == "Bearing"


def test_unstocked_part_deactivates_without_confirmation(store):
    result = InventoryBridge(store).set_part_active({"part_number": "B", "active": False})
    assert result["ok"] is True
    assert store.parts["B"].active is False


def test_invalid_active_requests_are_rejected(store):
    bridge = InventoryBridge(store)
    for invalid in (
        None,
        [],
        {"part_number": "A"},
        {"part_number": "A", "active": "no"},
        {"part_number": "A", "active": 0},
        {"part_number": "A", "active": False, "confirm_stock": "yes"},
        {"part_number": "A", "active": False, "extra": 1},
        {"active": False},
    ):
        assert bridge.set_part_active(invalid)["error"]["code"] == "VALIDATION", invalid
    assert (
        bridge.set_part_active({"part_number": "missing", "active": True})["error"]["code"]
        == "NOT_FOUND"
    )
    assert store.parts["A"].active is True


def test_edit_failure_is_safe_and_leaves_part_unchanged(store, monkeypatch, caplog):
    bridge = InventoryBridge(store)

    def fail(*args, **kwargs):
        raise RuntimeError("private technical detail")

    monkeypatch.setattr(store, "update_part", fail)
    result = bridge.update_part(edit())
    assert result["error"]["code"] == "INTERNAL"
    assert "private technical detail" not in json.dumps(result)
    monkeypatch.undo()
    assert bridge.part_detail("A")["data"]["description"] == "Bearing"
