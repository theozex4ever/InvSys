"""Reviewer's complete journey at the agreed bridge/real SQLite boundary."""

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


def test_complete_standard_and_nested_bom_workflows_survive_restart(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    bridge = InventoryBridge(store)
    try:
        for number in ("KIT", "SUB", "LEAF"):
            assert bridge.create_part(
                dict(
                    part_number=number,
                    description=f"Review {number}",
                    minimum_quantity=5,
                    location="Stock",
                )
            )["ok"]
        # Existing BOM definitions remain maintained by the original application.
        store.add_bom_component("KIT", "SUB", 2)
        store.add_bom_component("SUB", "LEAF", 3)
        store.add_bom_component("KIT", "LEAF", 1)
        assert (
            bridge.search_parts({"query": "Review LEAF"})["data"][0]["part_number"]
            == "LEAF"
        )
        assert bridge.save_operator("Pat")["ok"]
        assert bridge.save_theme("dark")["ok"]

        receipt = dict(
            part_number="LEAF",
            quantity=5,
            location="Stock",
            lot_number="",
            operator="Pat",
            reference="OPENING",
            notes="Checked at receiving",
        )
        before = bridge.stock_context("LEAF")
        assert bridge.receive(receipt)["error"]["code"] == "VALIDATION"
        assert bridge.stock_context("LEAF") == before
        for number, quantity, lot in (
            ("LEAF", 5, "A"),
            ("LEAF", 15, "B"),
            ("KIT", 10, "PARENT"),
            ("SUB", 10, "INTERMEDIATE"),
        ):
            assert bridge.receive(
                {
                    **receipt,
                    "part_number": number,
                    "quantity": quantity,
                    "lot_number": lot,
                }
            )["ok"]

        standard = dict(
            part_number="LEAF",
            quantity=6,
            location="Stock",
            lot_number="A",
            operator="Pat",
            recipient="Standard customer",
            reference="ORDER-STANDARD",
        )
        before = bridge.stock_context("LEAF")
        assert bridge.preview_ship(standard)["error"]["code"] == "VALIDATION"
        assert bridge.stock_context("LEAF") == before
        standard["quantity"] = 2
        review = bridge.preview_ship(standard)["data"]
        assert (review["lot_stock"], review["location_stock"], review["remaining"]) == (
            5,
            20,
            3,
        )
        standard_number = bridge.ship(standard)["data"]["shipment_number"]
        standard_trace = bridge.shipment_detail(standard_number)["data"]
        assert standard_trace["transactions"][0]["lot_number"] == "A"
        assert standard_trace["consumed_components"] == []

        bom = {**standard, "part_number": "KIT", "recipient": "BOM customer"}
        del bom["lot_number"]
        bom["reference"] = "ORDER-BOM"
        shortage = bridge.preview_bom_ship({**bom, "quantity": 3})["data"]
        assert not shortage["plan"]["ready"]
        before = {p: bridge.stock_context(p) for p in ("KIT", "SUB", "LEAF")}
        assert not bridge.ship_bom(
            {**bom, "quantity": 3, "review_id": shortage["review_id"]}
        )["ok"]
        assert {p: bridge.stock_context(p) for p in before} == before
        review = bridge.preview_bom_ship(bom)["data"]
        assert bridge.receive({**receipt, "lot_number": "0", "quantity": 2})["ok"]
        before = {p: bridge.stock_context(p) for p in before}
        assert (
            bridge.ship_bom({**bom, "review_id": review["review_id"]})["error"]["code"]
            == "PLAN_CHANGED"
        )
        assert {p: bridge.stock_context(p) for p in before} == before
        review = bridge.preview_bom_ship(bom)["data"]
        bom_number = bridge.ship_bom({**bom, "review_id": review["review_id"]})["data"][
            "shipment_number"
        ]
        bom_trace = bridge.shipment_detail(bom_number)["data"]
        assert bom_trace["consumed_components"] == [
            dict(part_number="LEAF", lot_number="0", location="Stock", quantity=2),
            dict(part_number="LEAF", lot_number="A", location="Stock", quantity=3),
            dict(part_number="LEAF", lot_number="B", location="Stock", quantity=9),
        ]
        assert (
            int(bom_number.rsplit("-", 1)[1])
            == int(standard_number.rsplit("-", 1)[1]) + 1
        )
        assert [bridge.part_detail(p)["data"]["quantity"] for p in before] == [
            10,
            10,
            6,
        ]
        assert bridge.dashboard()["data"]["shipment_count"] == 2
        for tx in bom_trace["transactions"]:
            assert (
                bridge.history_detail(tx["transaction_id"])["data"]["shipment"]
                == bom_trace
            )
        history = bridge.history({})["data"]
        assert history["total"] == 10
        contexts = {p: bridge.stock_context(p)["data"] for p in before}
    finally:
        store.engine.dispose()

    reopened = InventoryStore(path, seed=False)
    try:
        bridge = InventoryBridge(reopened)
        assert bridge.preferences()["data"] == dict(operator="Pat", theme="dark")
        assert bridge.history({})["data"] == history
        assert {p: bridge.stock_context(p)["data"] for p in contexts} == contexts
        for number, trace in (
            (standard_number, standard_trace),
            (bom_number, bom_trace),
        ):
            assert bridge.shipment_detail(number)["data"] == trace
    finally:
        reopened.engine.dispose()
