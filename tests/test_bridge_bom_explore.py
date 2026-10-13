"""BOM exploration through the public desktop bridge against real temporary SQLite."""

import json

import pytest

from inventory_control.bridge import InventoryBridge
from inventory_control.orm import BOMComponentRecord, PartRecord
from inventory_control.store import InventoryStore


@pytest.fixture
def bom(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    for number in ("KIT", "SUB", "LEAF", "BOLT"):
        store.add_part(number, f"{number} description")
    store.add_bom_component("KIT", "SUB", 2)
    store.add_bom_component("SUB", "LEAF", 3)
    store.add_bom_component("KIT", "LEAF", 1)
    store.add_bom_component("SUB", "BOLT", 1)
    store.receive("KIT", 10, "Stock", "PARENT", "Setup")
    store.receive("SUB", 10, "Stock", "INTERMEDIATE", "Setup")
    store.receive("LEAF", 5, "Stock", "A", "Setup")
    store.receive("LEAF", 15, "Stock", "B", "Setup")
    store.receive("BOLT", 40, "Stock", "BOLTS", "Setup")
    store.receive("LEAF", 99, "Receiving", "ELSEWHERE", "Setup")
    yield store, InventoryBridge(store), path
    store.engine.dispose()


def explore(bridge, **changes):
    return bridge.explore_bom({"part_number": "KIT", "quantity": 2, "location": "Stock", **changes})


def snapshot(bridge, store):
    return (
        {p: bridge.stock_context(p) for p in ("KIT", "SUB", "LEAF", "BOLT")},
        bridge.history({})["data"]["total"],
        store.bom_components,
    )


def test_nested_structure_and_shared_leaf_requirements_come_from_python(bom):
    store, bridge, _ = bom
    before = snapshot(bridge, store)
    result = explore(bridge)
    assert result["ok"]
    data = result["data"]
    json.dumps(data, allow_nan=False)
    assert data["has_bom"] is True
    assert data["request"] == {"part_number": "KIT", "quantity": 2, "location": "Stock"}
    # LEAF is shared: 2 builds x (1 direct + 2 SUB x 3) = 14, aggregated across both paths.
    assert data["requirements"] == [
        dict(
            part_number="BOLT",
            description="BOLT description",
            quantity_required=4,
            stock_available=40,
            shortage=0,
        ),
        dict(
            part_number="LEAF",
            description="LEAF description",
            quantity_required=14,
            stock_available=20,
            shortage=0,
        ),
    ]
    # Capacity counts single final products; only the selected Location counts.
    assert data["buildable"] == 2
    assert data["level"] == "critical"
    assert data["shortage_count"] == 0

    root = data["tree"]
    assert (root["part_number"], root["quantity_required"], root["children"][0]["part_number"]) == (
        "KIT",
        2,
        "LEAF",
    )
    leaf_direct, sub = root["children"]
    assert (leaf_direct["part_number"], leaf_direct["quantity_per_parent"]) == ("LEAF", 1)
    assert leaf_direct["capacity"] == 2  # aggregated shared requirement, not 20 // 1
    assert (sub["part_number"], sub["quantity_per_parent"], sub["quantity_required"]) == (
        "SUB",
        2,
        4,
    )
    assert [child["part_number"] for child in sub["children"]] == ["BOLT", "LEAF"]
    assert sub["capacity"] == min(child["capacity"] for child in sub["children"])
    assert root["capacity"] == 2
    assert sub["children"][1]["stock_available"] == 20
    # Phantom assemblies report their own stock without consuming or including it in capacity.
    assert (root["stock_available"], sub["stock_available"]) == (10, 10)
    # Exploring is read-only.
    assert snapshot(bridge, store) == before


@pytest.mark.parametrize(
    "leaf_stock, buildable, level",
    [
        (0, 0, "critical"),
        (200, 100, "critical"),
        (202, 101, "low"),
        (1000, 500, "low"),
        (1002, 501, "ready"),
    ],
)
def test_capacity_warning_boundaries(tmp_path, leaf_stock, buildable, level):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("KIT", "Kit")
    store.add_part("SCREW", "Screw")
    store.add_bom_component("KIT", "SCREW", 2)
    if leaf_stock:
        store.receive("SCREW", leaf_stock, "Stock", "L1", "Setup")
    data = InventoryBridge(store).explore_bom(
        {"part_number": "KIT", "quantity": 1, "location": "Stock"}
    )["data"]
    assert (data["buildable"], data["level"]) == (buildable, level)
    assert data["tree"]["children"][0]["level"] == level
    store.engine.dispose()


def test_capacity_warning_is_separate_from_shipment_shortage(bom):
    store, bridge, _ = bom
    # 20 LEAF supports 2 builds (critical) and 3 builds is a shortage for this order.
    short = explore(bridge, quantity=3)["data"]
    assert short["level"] == "critical"
    assert short["shortage_count"] == 1
    assert [r["shortage"] for r in short["requirements"]] == [0, 1]
    # Plenty of capacity (ready) can still be short for a larger requested quantity.
    store.receive("LEAF", 5000, "Stock", "C", "Setup")
    store.receive("BOLT", 5000, "Stock", "BOLTS2", "Setup")
    big = explore(bridge, quantity=1000)["data"]
    assert big["buildable"] == 5020 // 7
    assert big["level"] == "ready"
    assert big["shortage_count"] == 1
    assert big["requirements"][1]["shortage"] == 7000 - 5020
    # A request within stock has no shortage whatever the capacity level.
    small = explore(bridge, quantity=1)["data"]
    assert (small["level"], small["shortage_count"]) == ("ready", 0)


def test_changed_inventory_is_refreshed_and_location_is_respected(bom):
    store, bridge, _ = bom
    assert explore(bridge)["data"]["buildable"] == 2
    store.receive("LEAF", 21, "Stock", "C", "Other")
    assert explore(bridge)["data"]["buildable"] == 5
    elsewhere = explore(bridge, location="Receiving")["data"]
    assert elsewhere["buildable"] == 0
    assert elsewhere["shortage_count"] == 1  # BOLT has no Receiving stock; LEAF has plenty
    leaf = next(r for r in elsewhere["requirements"] if r["part_number"] == "LEAF")
    assert (leaf["stock_available"], leaf["shortage"]) == (99, 0)


def test_part_without_bom_is_a_single_node(bom):
    _, bridge, _ = bom
    data = bridge.explore_bom({"part_number": "leaf", "quantity": 1, "location": "Stock"})["data"]
    assert data["has_bom"] is False
    assert data["requirements"] == []
    assert data["tree"]["children"] == []
    assert data["tree"]["stock_available"] == 20


def test_inactive_root_is_explorable_but_shortage_status_is_not_shipping_eligibility(bom):
    store, bridge, _ = bom
    store.set_part_active("KIT", False)
    data = explore(bridge)["data"]
    assert data["shortage_count"] == 0
    # Shipment review, not exploration, decides eligibility.
    review = bridge.preview_bom_ship(
        {
            "part_number": "KIT",
            "quantity": 2,
            "location": "Stock",
            "operator": "Pat",
            "recipient": "Customer",
        }
    )
    assert review["ok"] is False
    assert "inactive" in review["error"]["message"]


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"part_number": "NOPE"}, "NOT_FOUND"),
        ({"part_number": ""}, "VALIDATION"),
        ({"part_number": 7}, "VALIDATION"),
        ({"location": "Nowhere"}, "VALIDATION"),
        ({"location": None}, "VALIDATION"),
        ({"quantity": 0}, "VALIDATION"),
        ({"quantity": -1}, "VALIDATION"),
        ({"quantity": True}, "VALIDATION"),
        ({"quantity": "2"}, "VALIDATION"),
        ({"quantity": 2**31}, "VALIDATION"),
        ({"surprise": 1}, "VALIDATION"),
    ],
)
def test_invalid_requests_return_safe_errors(bom, changes, code):
    store, bridge, _ = bom
    before = snapshot(bridge, store)
    result = explore(bridge, **changes)
    assert result["ok"] is False
    assert result["error"]["code"] == code
    assert result["error"]["message"]
    assert snapshot(bridge, store) == before


def test_non_object_request_is_rejected(bom):
    _, bridge, _ = bom
    assert bridge.explore_bom("KIT")["error"]["code"] == "VALIDATION"
    assert bridge.explore_bom(None)["error"]["code"] == "VALIDATION"


def test_circular_definition_is_reported_without_a_stack_trace(bom):
    store, bridge, _ = bom
    # Authoring rejects cycles; simulate an invalid definition written outside the service.
    with store.session_factory() as session:
        leaf = session.query(PartRecord).filter_by(part_number="LEAF").one()
        kit = session.query(PartRecord).filter_by(part_number="KIT").one()
        session.add(
            BOMComponentRecord(parent_part_id=leaf.id, component_part_id=kit.id, quantity_per=1)
        )
        session.commit()
    result = explore(bridge)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION"
    assert "circular" in result["error"]["message"].lower()


def test_inactive_component_is_reported_as_an_invalid_definition(bom):
    store, bridge, _ = bom
    store.set_part_active("BOLT", False)
    result = explore(bridge)
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION"
    assert "BOLT" in result["error"]["message"]


def test_very_large_expansion_is_refused_before_it_can_freeze_the_view(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    levels = 14
    for level in range(levels + 1):
        store.add_part(f"A{level}", "Assembly")
    for level in range(levels):
        for side in "BC":
            store.add_part(f"{side}{level}", "Branch")
            store.add_bom_component(f"A{level}", f"{side}{level}", 1)
            store.add_bom_component(f"{side}{level}", f"A{level + 1}", 1)
    result = InventoryBridge(store).explore_bom(
        {"part_number": "A0", "quantity": 1, "location": "Stock"}
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION"
    assert "too large" in result["error"]["message"].lower()
    store.engine.dispose()


def test_unexpected_failure_returns_safe_message(bom, monkeypatch):
    store, bridge, _ = bom

    def broken(*_args, **_kwargs):
        raise RuntimeError("database is locked at /secret/path")

    monkeypatch.setattr(store, "explore_bom", broken)
    result = explore(bridge)
    assert result["error"]["code"] == "INTERNAL"
    assert "secret" not in result["error"]["message"]
