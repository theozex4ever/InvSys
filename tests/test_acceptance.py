"""Migration fixtures observed through the public API and real SQLite."""

import json

import pytest

from inventory_control.acceptance import create_fixture
from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


def test_workflow_fixture_survives_restart_and_supports_delivered_workflows(tmp_path):
    directory = tmp_path / "acceptance"
    path = create_fixture(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    assert (manifest["parts"], manifest["transactions"]) == (5, 15)
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)
    assert bridge.part_detail("INACTIVE")["data"]["active"] is False
    assert store.stock_at("STANDARD", "Stock", "ZERO") == 0
    assert {lot.lot_number for lot in store.lots_for_part("STANDARD", "Stock")} == {
        "A",
        "B",
        "ZERO",
    }
    assert bridge.dashboard()["data"]["shipment_count"] == 2
    assert bridge.preferences()["data"] == {"operator": "Acceptance operator", "theme": "dark"}
    historical = [bridge.shipment_detail(n)["data"] for n in manifest["shipments"]]
    assert historical[1]["consumed_components"] == [
        dict(part_number="LEAF", lot_number="A", location="Stock", quantity=5),
        dict(part_number="LEAF", lot_number="B", location="Stock", quantity=9),
    ]
    receipt = dict(
        part_number="STANDARD",
        quantity=3,
        location="Stock",
        lot_number="NEW",
        operator="Acceptance operator",
        reference="ACCEPT-NEW",
        notes="Restart receipt",
    )
    assert bridge.receive(receipt)["ok"]
    standard = dict(
        part_number="STANDARD",
        quantity=2,
        location="Stock",
        lot_number="NEW",
        operator="Acceptance operator",
        recipient="Customer",
    )
    assert bridge.preview_ship(standard)["data"]["remaining"] == 1
    assert bridge.ship(standard)["ok"]
    bom = dict(
        part_number="KIT",
        quantity=1,
        location="Stock",
        operator="Acceptance operator",
        recipient="Kit customer",
    )
    review = bridge.preview_bom_ship(bom)["data"]
    assert bridge.ship_bom({**bom, "review_id": review["review_id"]})["ok"]
    assert not bridge.preview_bom_ship({**bom, "quantity": 100})["data"]["plan"]["ready"]
    assert [store.total_stock(p) for p in ("KIT", "SUB")] == [10, 10]
    store.add_bom_component("SUB", "LEAF", 4)
    history = bridge.history({})["data"]
    context = bridge.stock_context("STANDARD")["data"]
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    bridge = InventoryBridge(reopened)
    assert bridge.history({})["data"] == history
    assert bridge.stock_context("STANDARD")["data"] == context
    assert [bridge.shipment_detail(n)["data"] for n in manifest["shipments"]] == historical


def test_fixture_refuses_existing_directory_without_touching_inventory(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    store.add_part("KEEP", "Operational sentinel")
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        create_fixture(tmp_path)
    assert path.read_bytes() == before
    assert list(store.parts) == ["KEEP"]


@pytest.mark.timeout(600)
def test_large_fixture_has_approved_scale_and_usable_bom(tmp_path):
    path = create_fixture(tmp_path / "large", large=True)
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)
    assert len(store.parts) == 10000
    assert bridge.history({})["data"]["total"] == 100000
    availability = store.bom_availability("PERF-ROOT", 1, "Stock")
    nodes = [availability.tree]
    count = 0
    while nodes:
        node = nodes.pop()
        count += 1
        nodes.extend(node.children)
    assert count == 1000
    assert len(availability.requirements) == 900
    assert availability.buildable > 0
    assert {lot.lot_number for lot in store.lots_for_part("PERF-00100")} == {
        "PERF-LOT-0",
        "PERF-LOT-1",
        "PERF-LOT-2",
    }
    assert bridge.preview_bom_ship(
        dict(
            part_number="PERF-ROOT",
            quantity=1,
            location="Stock",
            recipient="Performance customer",
            operator="Acceptance operator",
        )
    )["data"]["plan"]["ready"]
