import json

import pytest

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


@pytest.fixture
def bom(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    for number in ("KIT", "SUB", "LEAF"):
        store.add_part(number, number)
    store.add_bom_component("KIT", "SUB", 2)
    store.add_bom_component("SUB", "LEAF", 3)
    store.add_bom_component("KIT", "LEAF", 1)
    store.receive("KIT", 10, "Stock", "PARENT", "Setup")
    store.receive("SUB", 10, "Stock", "INTERMEDIATE", "Setup")
    store.receive("LEAF", 5, "Stock", "A", "Setup")
    store.receive("LEAF", 15, "Stock", "B", "Setup")
    yield store, InventoryBridge(store), path
    store.engine.dispose()


def request(**changes):
    return dict(
        part_number="KIT",
        quantity=2,
        location="Stock",
        operator="Pat",
        recipient="Customer",
        reference="ORDER-BOM",
        **changes,
    )


def test_reviewed_nested_shared_leaf_consumes_multiple_lots_and_persists_trace(bom):
    store, bridge, path = bom
    draft = request()
    review = bridge.preview_bom_ship(draft)["data"]
    assert review["plan"]["ready"] is True
    assert review["buildable"] == 2
    assert review["plan"]["requirements"] == [
        dict(
            part_number="LEAF",
            description="LEAF",
            quantity_required=14,
            stock_available=20,
            shortage=0,
        )
    ]
    assert [
        (line["lot_number"], line["quantity_allocated"]) for line in review["plan"]["lines"]
    ] == [("A", 5), ("B", 9)]
    json.dumps(review)
    result = bridge.ship_bom({**draft, "review_id": review["review_id"]})
    assert result["ok"]
    number = result["data"]["shipment_number"]
    assert bridge.part_detail("KIT")["data"]["quantity"] == 10
    assert bridge.part_detail("SUB")["data"]["quantity"] == 10
    assert bridge.part_detail("LEAF")["data"]["quantity"] == 6
    detail = bridge.shipment_detail(number)["data"]
    assert detail["reference"] == "ORDER-BOM"
    assert detail["consumed_components"] == [
        dict(part_number="LEAF", lot_number="A", location="Stock", quantity=5),
        dict(part_number="LEAF", lot_number="B", location="Stock", quantity=9),
    ]
    assert [tx["tx_type"] for tx in detail["transactions"]] == [
        "SHIP_BOM",
        "BOM_CONSUME",
        "BOM_CONSUME",
    ]
    assert (
        bridge.history_detail(detail["transactions"][1]["transaction_id"])["data"]["shipment"]
        == detail
    )
    assert bridge.ship_bom({**draft, "review_id": review["review_id"]})["ok"] is False
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    assert InventoryBridge(reopened).shipment_detail(number)["data"] == detail
    reopened.engine.dispose()


def test_changed_allocation_rejects_without_effects_and_requires_fresh_review(bom):
    store, bridge, _ = bom
    draft = request()
    review = bridge.preview_bom_ship(draft)["data"]
    store.receive("LEAF", 2, "Stock", "0", "Other")
    before = {p: bridge.stock_context(p) for p in ("KIT", "SUB", "LEAF")}
    result = bridge.ship_bom({**draft, "review_id": review["review_id"]})
    assert result["error"]["code"] == "PLAN_CHANGED"
    assert {p: bridge.stock_context(p) for p in before} == before
    assert bridge.history(dict(tx_type="BOM_CONSUME"))["data"]["records"] == []
    assert bridge.ship_bom({**draft, "review_id": review["review_id"]})["ok"] is False
    updated = bridge.preview_bom_ship(draft)["data"]
    assert [
        (line["lot_number"], line["quantity_allocated"]) for line in updated["plan"]["lines"]
    ] == [("0", 2), ("A", 5), ("B", 7)]
    assert bridge.ship_bom({**draft, "review_id": updated["review_id"]})["ok"]


def test_shortage_preview_is_read_only_and_cannot_authorize_submission(bom):
    _, bridge, _ = bom
    draft = {**request(), "quantity": 3}
    before = {p: bridge.stock_context(p) for p in ("KIT", "SUB", "LEAF")}
    review = bridge.preview_bom_ship(draft)["data"]
    assert review["plan"]["ready"] is False
    assert review["plan"]["requirements"][0]["shortage"] == 1
    assert review["buildable"] == 2
    assert review["review_id"] == ""
    assert bridge.ship_bom({**draft, "review_id": review["review_id"]})["ok"] is False
    assert {p: bridge.stock_context(p) for p in before} == before


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"review_id": "invented"},
        {"review_id": True},
        {"plan": {}},
        {"review_id": []},
    ],
)
def test_bom_submission_cannot_skip_or_fabricate_review(bom, invalid):
    _, bridge, _ = bom
    before = bridge.stock_context("LEAF")
    assert bridge.ship_bom({**request(), **invalid})["error"]["code"] == "VALIDATION"
    assert bridge.stock_context("LEAF") == before


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": 1},
        {"operator": "Other"},
        {"recipient": "Other"},
        {"reference": "Other"},
        {"location": "Receiving"},
    ],
)
def test_review_is_bound_to_exact_draft(bom, change):
    _, bridge, _ = bom
    review = bridge.preview_bom_ship(request())["data"]
    before = bridge.stock_context("LEAF")
    assert (
        bridge.ship_bom({**request(), **change, "review_id": review["review_id"]})["error"]["code"]
        == "VALIDATION"
    )
    assert bridge.stock_context("LEAF") == before


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        {"quantity": True},
        {"quantity": 0},
        {"quantity": 1.2},
        {"quantity": "2"},
        {"quantity": 2**31},
        {"operator": ""},
        {"recipient": []},
        {"location": "missing"},
        {"lot_number": "PARENT"},
        {"plan": {}},
        {"review_id": "x"},
    ],
)
def test_invalid_bom_review_requests_are_rejected(bom, invalid):
    _, bridge, _ = bom
    before = bridge.stock_context("LEAF")
    response = bridge.preview_bom_ship(
        {**request(), **invalid} if isinstance(invalid, dict) else invalid
    )
    assert response["error"]["code"] == "VALIDATION"
    assert bridge.stock_context("LEAF") == before


def test_review_does_not_trust_mutated_response_and_does_not_survive_bridge_restart(
    bom,
):
    store, bridge, _ = bom
    review = bridge.preview_bom_ship(request())["data"]
    review["plan"]["lines"][0]["quantity_allocated"] = 999
    restarted = InventoryBridge(store)
    assert restarted.ship_bom({**request(), "review_id": review["review_id"]})["ok"] is False
    assert bridge.ship_bom({**request(), "review_id": review["review_id"]})["ok"]
    assert bridge.part_detail("LEAF")["data"]["quantity"] == 6


def test_component_shortage_after_ready_review_rolls_back_all_trace(bom):
    store, bridge, _ = bom
    review = bridge.preview_bom_ship(request())["data"]
    store.ship("LEAF", 10, "Stock", "Other", "Other", lot_number="B")
    before = {p: bridge.stock_context(p) for p in ("KIT", "SUB", "LEAF")}
    assert bridge.ship_bom({**request(), "review_id": review["review_id"]})["ok"] is False
    assert {p: bridge.stock_context(p) for p in before} == before
    assert bridge.history({"tx_type": "SHIP_BOM"})["data"]["records"] == []
    assert bridge.history({"tx_type": "BOM_CONSUME"})["data"]["records"] == []


def test_snapshot_reads_survive_later_bom_definition_changes(bom):
    store, bridge, _ = bom
    review = bridge.preview_bom_ship(request())["data"]
    number = bridge.ship_bom({**request(), "review_id": review["review_id"]})["data"][
        "shipment_number"
    ]
    before = bridge.shipment_detail(number)
    store.remove_bom_component("SUB", "LEAF")
    store.remove_bom_component("KIT", "LEAF")
    assert bridge.shipment_detail(number) == before
    assert (
        bridge.history_detail(before["data"]["transactions"][0]["transaction_id"])["data"][
            "shipment"
        ]
        == before["data"]
    )


def test_bom_custom_shipment_reference_search_includes_parent_and_consumption(bom):
    _, bridge, _ = bom
    review = bridge.preview_bom_ship(request())["data"]
    bridge.ship_bom({**request(), "review_id": review["review_id"]})
    records = bridge.history({"query": "order-bom"})["data"]["records"]
    assert [tx["tx_type"] for tx in records] == [
        "SHIP_BOM",
        "BOM_CONSUME",
        "BOM_CONSUME",
    ]
