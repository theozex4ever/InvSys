import json

import pytest

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


@pytest.fixture
def authoring(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    for number in ("KIT", "SUB", "LEAF", "BOLT", "LOOSE"):
        store.add_part(number, f"{number} part")
    yield store, InventoryBridge(store), path
    store.engine.dispose()


def save(bridge, parent, component, quantity_per):
    return bridge.save_bom_component(
        {"parent": parent, "component": component, "quantity_per": quantity_per}
    )


def components(bridge, parent):
    return [
        (c["part_number"], c["quantity_per"])
        for c in bridge.bom_definition(parent)["data"]["components"]
    ]


def test_part_without_definition_reads_empty_and_unknown_part_is_not_found(authoring):
    _, bridge, _ = authoring
    definition = bridge.bom_definition("kit")["data"]
    assert definition["part"] == {
        "part_number": "KIT",
        "description": "KIT part",
        "active": True,
        "has_bom": False,
    }
    assert definition["components"] == []
    assert definition["used_in"] == []
    assert bridge.bom_definition("MISSING")["error"]["code"] == "NOT_FOUND"
    assert bridge.bom_definition(7)["error"]["code"] == "VALIDATION"
    json.dumps(definition, allow_nan=False)


def test_nested_and_shared_definitions_are_authored_and_read_back(authoring):
    _, bridge, _ = authoring
    added = save(bridge, "KIT", "SUB", 2)
    assert added["data"]["action"] == "added"
    assert save(bridge, "SUB", "LEAF", 3)["ok"]
    assert save(bridge, "KIT", "LEAF", 1)["ok"]
    kit = bridge.bom_definition("KIT")["data"]
    assert [
        (c["part_number"], c["description"], c["quantity_per"], c["has_bom"], c["active"])
        for c in kit["components"]
    ] == [
        ("LEAF", "LEAF part", 1, False, True),
        ("SUB", "SUB part", 2, True, True),
    ]
    assert kit["part"]["has_bom"] is True
    leaf = bridge.bom_definition("LEAF")["data"]
    assert [(u["part_number"], u["quantity_per"]) for u in leaf["used_in"]] == [
        ("KIT", 1),
        ("SUB", 3),
    ]
    assert save(bridge, "KIT", "LEAF", 1)["data"]["definition"] == kit


def test_adding_existing_component_updates_quantity_without_duplicate_link(authoring):
    store, bridge, _ = authoring
    save(bridge, "KIT", "LEAF", 1)
    updated = save(bridge, "KIT", "leaf", 5)
    assert updated["data"]["action"] == "updated"
    assert components(bridge, "KIT") == [("LEAF", 5)]
    assert store.bom_components == {"KIT": {"LEAF": 5}}
    assert updated["data"]["definition"] == bridge.bom_definition("KIT")["data"]


@pytest.mark.parametrize(
    "parent, component, quantity, message",
    [
        ("KIT", "KIT", 1, "cannot contain itself"),
        ("LEAF", "KIT", 1, "circular"),
        ("SUB", "KIT", 1, "circular"),
        ("KIT", "SUB", 0, "greater than zero"),
        ("KIT", "SUB", -2, "greater than zero"),
        ("KIT", "SUB", 2**31, "cannot exceed 2147483647"),
        ("KIT", "SUB", 1.5, "whole number"),
        ("KIT", "SUB", "2", "whole number"),
        ("KIT", "SUB", True, "whole number"),
        ("KIT", "NOPE", 1, "Part not found"),
        ("NOPE", "SUB", 1, "Part not found"),
        ("", "SUB", 1, "required"),
        ("KIT", None, 1, "must be text"),
    ],
)
def test_invalid_saves_are_rejected_and_leave_definitions_unchanged(
    authoring, parent, component, quantity, message
):
    store, bridge, _ = authoring
    store.add_bom_component("KIT", "SUB", 2)
    store.add_bom_component("SUB", "LEAF", 3)
    before = store.bom_components
    response = save(bridge, parent, component, quantity)
    assert response["ok"] is False
    assert response["error"]["code"] == "VALIDATION"
    assert message in response["error"]["message"]
    assert store.bom_components == before


@pytest.mark.parametrize(
    "request_body",
    [
        None,
        [],
        {"parent": "KIT", "component": "SUB"},
        {"parent": "KIT", "component": "SUB", "quantity_per": 1, "x": 1},
    ],
)
def test_save_rejects_malformed_requests(authoring, request_body):
    store, bridge, _ = authoring
    assert bridge.save_bom_component(request_body)["error"]["code"] == "VALIDATION"
    assert store.bom_components == {}


def test_removal_requires_confirmation_then_removes_only_that_link(authoring):
    store, bridge, _ = authoring
    save(bridge, "KIT", "SUB", 2)
    save(bridge, "KIT", "LEAF", 1)
    save(bridge, "SUB", "LEAF", 3)
    for confirmed in (None, False, "yes", 1):
        denied = bridge.remove_bom_component(
            {"parent": "KIT", "component": "LEAF", "confirmed": confirmed}
        )
        assert denied["error"]["code"] == "VALIDATION"
    assert bridge.remove_bom_component({"parent": "KIT", "component": "LEAF"})["ok"] is False
    assert components(bridge, "KIT") == [("LEAF", 1), ("SUB", 2)]
    removed = bridge.remove_bom_component({"parent": "KIT", "component": "LEAF", "confirmed": True})
    assert removed["data"]["definition"] == bridge.bom_definition("KIT")["data"]
    assert components(bridge, "KIT") == [("SUB", 2)]
    assert components(bridge, "SUB") == [("LEAF", 3)]
    missing = bridge.remove_bom_component({"parent": "KIT", "component": "LEAF", "confirmed": True})
    assert missing["error"]["code"] == "VALIDATION"
    assert "not on this BOM" in missing["error"]["message"]
    assert store.bom_components == {"KIT": {"SUB": 2}, "SUB": {"LEAF": 3}}


def test_definitions_persist_across_restart(authoring):
    store, bridge, path = authoring
    save(bridge, "KIT", "SUB", 2)
    save(bridge, "SUB", "LEAF", 3)
    save(bridge, "KIT", "SUB", 4)
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    try:
        assert components(InventoryBridge(reopened), "KIT") == [("SUB", 4)]
        assert components(InventoryBridge(reopened), "SUB") == [("LEAF", 3)]
    finally:
        reopened.engine.dispose()


def stocked(store):
    store.receive("KIT", 10, "Stock", "PARENT", "Setup")
    store.receive("SUB", 10, "Stock", "INTERMEDIATE", "Setup")
    store.receive("LEAF", 20, "Stock", "A", "Setup")
    store.receive("BOLT", 20, "Stock", "B", "Setup")


def ship_draft():
    return dict(
        part_number="KIT",
        quantity=2,
        location="Stock",
        operator="Pat",
        recipient="Customer",
        reference="ORDER",
    )


def test_edit_after_review_requires_fresh_review_and_leaves_stock_unchanged(authoring):
    store, bridge, _ = authoring
    stocked(store)
    save(bridge, "KIT", "SUB", 2)
    save(bridge, "SUB", "LEAF", 3)
    review = bridge.preview_bom_ship(ship_draft())["data"]
    assert review["plan"]["ready"] is True
    save(bridge, "SUB", "LEAF", 4)
    before = {p: bridge.stock_context(p) for p in ("KIT", "SUB", "LEAF", "BOLT")}
    stale = bridge.ship_bom({**ship_draft(), "review_id": review["review_id"]})
    assert stale["error"]["code"] == "PLAN_CHANGED"
    assert {p: bridge.stock_context(p) for p in before} == before
    assert bridge.history({"tx_type": "SHIP_BOM"})["data"]["records"] == []
    again = bridge.ship_bom({**ship_draft(), "review_id": review["review_id"]})
    assert again["ok"] is False
    fresh = bridge.preview_bom_ship(ship_draft())["data"]
    assert fresh["plan"]["requirements"][0]["quantity_required"] == 16
    assert bridge.ship_bom({**ship_draft(), "review_id": fresh["review_id"]})["ok"]
    assert bridge.part_detail("LEAF")["data"]["quantity"] == 4
    assert bridge.part_detail("KIT")["data"]["quantity"] == 10
    assert bridge.part_detail("SUB")["data"]["quantity"] == 10


def test_removing_last_component_invalidates_reviewed_bom_shipment(authoring):
    store, bridge, _ = authoring
    stocked(store)
    save(bridge, "KIT", "LEAF", 1)
    review = bridge.preview_bom_ship(ship_draft())["data"]
    bridge.remove_bom_component({"parent": "KIT", "component": "LEAF", "confirmed": True})
    before = bridge.stock_context("LEAF")
    assert bridge.ship_bom({**ship_draft(), "review_id": review["review_id"]})["ok"] is False
    assert bridge.stock_context("LEAF") == before
    assert bridge.history({"tx_type": "SHIP_BOM"})["data"]["records"] == []


def test_equivalent_edit_keeps_reviewed_plan_but_new_requirement_blocks_it(authoring):
    store, bridge, _ = authoring
    stocked(store)
    save(bridge, "KIT", "LEAF", 1)
    review = bridge.preview_bom_ship(ship_draft())["data"]
    # An unchanged definition is compatible with the reviewed plan.
    save(bridge, "KIT", "LEAF", 1)
    # A new unrelated assembly does not affect this plan either.
    save(bridge, "LOOSE", "BOLT", 1)
    assert bridge.ship_bom({**ship_draft(), "review_id": review["review_id"]})["ok"]
    review = bridge.preview_bom_ship(ship_draft())["data"]
    save(bridge, "KIT", "BOLT", 2)
    changed = bridge.ship_bom({**ship_draft(), "review_id": review["review_id"]})
    assert changed["error"]["code"] == "PLAN_CHANGED"


def test_historical_snapshots_are_unchanged_by_later_definition_edits(authoring):
    store, bridge, path = authoring
    stocked(store)
    save(bridge, "KIT", "SUB", 2)
    save(bridge, "SUB", "LEAF", 3)
    review = bridge.preview_bom_ship(ship_draft())["data"]
    number = bridge.ship_bom({**ship_draft(), "review_id": review["review_id"]})["data"][
        "shipment_number"
    ]
    before = bridge.shipment_detail(number)["data"]
    assert before["consumed_components"] == [
        dict(part_number="LEAF", lot_number="A", location="Stock", quantity=12)
    ]
    save(bridge, "SUB", "LEAF", 9)
    save(bridge, "SUB", "BOLT", 1)
    bridge.remove_bom_component({"parent": "KIT", "component": "SUB", "confirmed": True})
    assert bridge.shipment_detail(number)["data"] == before
    first = before["transactions"][0]["transaction_id"]
    assert bridge.history_detail(first)["data"]["shipment"] == before
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    try:
        assert InventoryBridge(reopened).shipment_detail(number)["data"] == before
    finally:
        reopened.engine.dispose()


def test_authoring_never_writes_stock_or_audit_records(authoring):
    store, bridge, _ = authoring
    stocked(store)
    before_stock = {p: bridge.stock_context(p) for p in ("KIT", "SUB", "LEAF", "BOLT")}
    before_history = bridge.history({})["data"]
    save(bridge, "KIT", "SUB", 2)
    save(bridge, "KIT", "SUB", 3)
    bridge.remove_bom_component({"parent": "KIT", "component": "SUB", "confirmed": True})
    assert {p: bridge.stock_context(p) for p in before_stock} == before_stock
    assert bridge.history({})["data"] == before_history
