"""
test_bom.py — Tests for nested bill-of-material shipping.

The current prototype treats BOM parents as phantom assemblies/kits: shipping
a BOM parent creates a shipment for the parent and deducts the leaf component
parts required by the nested BOM. Intermediate assemblies are visual trace
nodes, not inventory deductions.
"""

import pytest

from inventory_control.models import LotAllocation


def build_nested_bom(store):
    store.add_part("KIT-001", "Service Kit")
    store.add_part("SUB-001", "Nested Subassembly")
    store.add_part("SCREW-001", "Socket Screw")
    store.add_part("NUT-001", "Lock Nut")
    store.add_bom_component("KIT-001", "SUB-001", 2)
    store.add_bom_component("SUB-001", "SCREW-001", 3)
    store.add_bom_component("KIT-001", "NUT-001", 4)


def kit_component_lots(qty: int) -> list[LotAllocation]:
    return [
        LotAllocation("NUT-001", "LOT-1", "Stock", 4 * qty),
        LotAllocation("SCREW-001", "LOT-1", "Stock", 6 * qty),
    ]


class TestBOMSetup:
    def test_add_bom_component_records_direct_child(self, blank_store):
        blank_store.add_part("KIT-001", "Service Kit")
        blank_store.add_part("SCREW-001", "Socket Screw")

        blank_store.add_bom_component("KIT-001", "SCREW-001", 4)

        children = blank_store.bom_children("KIT-001")
        assert len(children) == 1
        assert children[0].component_part_number == "SCREW-001"
        assert children[0].quantity_per == 4

    def test_component_quantity_must_be_positive(self, blank_store):
        blank_store.add_part("KIT-001", "Service Kit")
        blank_store.add_part("SCREW-001", "Socket Screw")

        with pytest.raises(ValueError, match="Component quantity must be greater than zero"):
            blank_store.add_bom_component("KIT-001", "SCREW-001", 0)

    def test_bom_cycles_are_rejected(self, blank_store):
        blank_store.add_part("KIT-001", "Service Kit")
        blank_store.add_part("SUB-001", "Nested Subassembly")
        blank_store.add_bom_component("KIT-001", "SUB-001", 1)

        with pytest.raises(ValueError, match="circular BOM"):
            blank_store.add_bom_component("SUB-001", "KIT-001", 1)


class TestNestedBOMRequirements:
    def test_nested_requirements_expand_to_leaf_components(self, blank_store):
        build_nested_bom(blank_store)

        requirements = blank_store.bom_requirements("KIT-001", 2, "Stock")
        required_by_part = {req.part_number: req.quantity_required for req in requirements}

        assert required_by_part == {
            "NUT-001": 8,
            "SCREW-001": 12,
        }

    def test_requirements_include_availability_and_shortage(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 10, "Stock", "LOT-1", "setup")

        requirements = blank_store.bom_requirements("KIT-001", 2, "Stock")
        screw = next(req for req in requirements if req.part_number == "SCREW-001")

        assert screw.stock_available == 10
        assert screw.shortage == 2


class TestBOMShip:
    def test_shipping_bom_parent_deducts_leaf_components(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        blank_store.ship("KIT-001", 2, "Stock", "Acme", "alice", component_lots=kit_component_lots(2))

        assert blank_store.stock_at("SCREW-001", "Stock") == 8
        assert blank_store.stock_at("NUT-001", "Stock") == 12

    def test_shipping_bom_parent_does_not_deduct_intermediate_assembly(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SUB-001", 5, "Stock", "LOT-1", "setup")
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        blank_store.ship("KIT-001", 1, "Stock", "Acme", "alice", component_lots=kit_component_lots(1))

        assert blank_store.stock_at("SUB-001", "Stock") == 5

    def test_bom_ship_creates_parent_shipment_and_component_trace(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        shipment_number = blank_store.ship("KIT-001", 2, "Stock", "Acme", "alice", component_lots=kit_component_lots(2))

        shipment = blank_store.shipments[0]
        assert shipment.shipment_number == shipment_number
        assert shipment.part_number == "KIT-001"
        assert {(c.part_number, c.quantity) for c in shipment.consumed_components} == {
            ("NUT-001", 8),
            ("SCREW-001", 12),
        }

    def test_bom_ship_creates_traceable_transactions(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        shipment_number = blank_store.ship("KIT-001", 1, "Stock", "Acme", "alice", component_lots=kit_component_lots(1))

        assert blank_store.transactions[0].tx_type == "SHIP_BOM"
        consume_transactions = [
            tx for tx in blank_store.transactions
            if tx.tx_type == "BOM_CONSUME" and tx.reference == shipment_number
        ]
        assert {tx.part_number for tx in consume_transactions} == {"NUT-001", "SCREW-001"}

    def test_bom_shortage_blocks_all_changes(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 2, "Stock", "LOT-1", "setup")
        before_transactions = len(blank_store.transactions)

        with pytest.raises(ValueError, match="Not enough BOM component stock"):
            blank_store.ship("KIT-001", 1, "Stock", "Acme", "alice", component_lots=kit_component_lots(1))

        assert blank_store.stock_at("SCREW-001", "Stock") == 2
        assert blank_store.stock_at("NUT-001", "Stock") == 0
        assert len(blank_store.shipments) == 0
        assert len(blank_store.transactions) == before_transactions
