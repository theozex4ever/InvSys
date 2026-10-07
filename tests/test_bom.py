"""
test_bom.py — Tests for nested bill-of-material shipping.

The current prototype treats BOM parents as phantom assemblies/kits: shipping
a BOM parent creates a shipment for the parent and deducts the leaf component
parts required by the nested BOM. Intermediate assemblies are visual trace
nodes, not inventory deductions.
"""

import pytest


def build_nested_bom(store):
    store.add_part("KIT-001", "Service Kit")
    store.add_part("SUB-001", "Nested Subassembly")
    store.add_part("SCREW-001", "Socket Screw")
    store.add_part("NUT-001", "Lock Nut")
    store.add_bom_component("KIT-001", "SUB-001", 2)
    store.add_bom_component("SUB-001", "SCREW-001", 3)
    store.add_bom_component("KIT-001", "NUT-001", 4)


def ship_kit(store, qty: int) -> str:
    plan = store.prepare_bom_shipment("KIT-001", qty, "Stock")
    return store.ship("KIT-001", qty, "Stock", "Acme", "alice", expected_bom_plan=plan)


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

        requirements = blank_store.bom_availability("KIT-001", 2, "Stock").requirements
        required_by_part = {req.part_number: req.quantity_required for req in requirements}

        assert required_by_part == {
            "NUT-001": 8,
            "SCREW-001": 12,
        }

    def test_requirements_include_availability_and_shortage(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 10, "Stock", "LOT-1", "setup")

        availability = blank_store.bom_availability("KIT-001", 2, "Stock")
        requirements = availability.requirements
        screw = next(req for req in requirements if req.part_number == "SCREW-001")

        assert screw.stock_available == 10
        assert screw.shortage == 2
        assert availability.tree.part_number == "KIT-001"
        assert availability.tree.children[0].quantity_required == 8
        assert availability.buildable == 0


class TestBOMBuildCapacity:
    def test_capacity_uses_final_product_units_and_selected_location(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 900, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 800, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 400, "Receiving", "LOT-2", "setup")

        availability = blank_store.bom_availability("KIT-001", 2, "Stock")

        assert availability.capacities == {"NUT-001": 200, "SCREW-001": 150}
        assert availability.buildable == 150
        assert availability.tree.children[0].stock_available == 800
        assert {req.part_number: req.quantity_required for req in availability.requirements} == {
            "NUT-001": 8,
            "SCREW-001": 12,
        }

    def test_shared_material_counts_all_branches(self, blank_store):
        for part in ("KIT", "LEFT", "RIGHT", "SCREW"):
            blank_store.add_part(part, part)
        blank_store.add_bom_component("KIT", "LEFT", 1)
        blank_store.add_bom_component("KIT", "RIGHT", 1)
        blank_store.add_bom_component("LEFT", "SCREW", 2)
        blank_store.add_bom_component("RIGHT", "SCREW", 3)
        blank_store.receive("SCREW", 504, "Stock", "LOT-1", "setup")

        availability = blank_store.bom_availability("KIT", 1, "Stock")
        assert (availability.buildable, availability.capacities) == (100, {"SCREW": 100})
        assert [(req.part_number, req.quantity_required) for req in availability.requirements] == [
            ("SCREW", 5)
        ]

    def test_part_without_bom_uses_its_own_stock(self, blank_store):
        blank_store.add_part("SINGLE", "Standalone")
        blank_store.receive("SINGLE", 501, "Stock", "LOT-1", "setup")

        availability = blank_store.bom_availability("SINGLE", 1, "Stock")
        assert (availability.buildable, availability.capacities) == (501, {"SINGLE": 501})
        assert availability.requirements == []
        assert availability.tree.stock_available == 501


class TestBOMShip:
    def test_shipping_bom_parent_deducts_leaf_components(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        ship_kit(blank_store, 2)

        assert blank_store.stock_at("SCREW-001", "Stock") == 8
        assert blank_store.stock_at("NUT-001", "Stock") == 12

    def test_shipping_bom_parent_does_not_deduct_intermediate_assembly(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SUB-001", 5, "Stock", "LOT-1", "setup")
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        ship_kit(blank_store, 1)

        assert blank_store.stock_at("SUB-001", "Stock") == 5

    def test_bom_ship_creates_parent_shipment_and_component_trace(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        shipment_number = ship_kit(blank_store, 2)

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

        shipment_number = ship_kit(blank_store, 1)

        assert blank_store.transactions[0].tx_type == "SHIP_BOM"
        consume_transactions = [
            tx
            for tx in blank_store.transactions
            if tx.tx_type == "BOM_CONSUME" and tx.reference == shipment_number
        ]
        assert {tx.part_number for tx in consume_transactions} == {"NUT-001", "SCREW-001"}

    def test_bom_shortage_blocks_all_changes(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 2, "Stock", "LOT-1", "setup")
        before_transactions = len(blank_store.transactions)
        plan = blank_store.prepare_bom_shipment("KIT-001", 1, "Stock")
        assert plan.ready is False

        with pytest.raises(ValueError, match="Not enough BOM component stock"):
            blank_store.ship("KIT-001", 1, "Stock", "Acme", "alice", expected_bom_plan=plan)

        assert blank_store.stock_at("SCREW-001", "Stock") == 2
        assert blank_store.stock_at("NUT-001", "Stock") == 0
        assert len(blank_store.shipments) == 0
        assert len(blank_store.transactions) == before_transactions

    def test_store_allocates_by_lot_number_across_multiple_lots(self, blank_store):
        blank_store.add_part("KIT", "Kit")
        blank_store.add_part("COMP", "Component")
        blank_store.add_bom_component("KIT", "COMP", 5)
        blank_store.receive("COMP", 3, "Stock", "LOT-B", "setup")
        blank_store.receive("COMP", 2, "Stock", "LOT-A", "setup")

        plan = blank_store.prepare_bom_shipment("KIT", 1, "Stock")

        assert plan.ready is True
        assert [(line.lot_number, line.quantity_allocated) for line in plan.lines] == [
            ("LOT-A", 2),
            ("LOT-B", 3),
        ]
        blank_store.ship("KIT", 1, "Stock", "Acme", "alice", expected_bom_plan=plan)
        assert {
            (item.lot_number, item.quantity)
            for item in blank_store.shipments[0].consumed_components
        } == {
            ("LOT-A", 2),
            ("LOT-B", 3),
        }

    def test_changed_lot_allocation_requires_review_without_writes(self, blank_store):
        blank_store.add_part("KIT", "Kit")
        blank_store.add_part("COMP", "Component")
        blank_store.add_bom_component("KIT", "COMP", 5)
        blank_store.receive("COMP", 5, "Stock", "LOT-B", "setup")
        plan = blank_store.prepare_bom_shipment("KIT", 1, "Stock")
        blank_store.receive("COMP", 1, "Stock", "LOT-A", "setup")
        before_transactions = len(blank_store.transactions)

        with pytest.raises(ValueError, match="allocation changed"):
            blank_store.ship("KIT", 1, "Stock", "Acme", "alice", expected_bom_plan=plan)

        assert blank_store.stock_at("COMP", "Stock") == 6
        assert blank_store.shipments == []
        assert len(blank_store.transactions) == before_transactions

    def test_unrelated_stock_change_keeps_reviewed_lots_valid(self, blank_store):
        blank_store.add_part("KIT", "Kit")
        blank_store.add_part("COMP", "Component")
        blank_store.add_bom_component("KIT", "COMP", 5)
        blank_store.receive("COMP", 5, "Stock", "LOT-A", "setup")
        plan = blank_store.prepare_bom_shipment("KIT", 1, "Stock")
        blank_store.receive("COMP", 1, "Stock", "LOT-B", "setup")

        blank_store.ship("KIT", 1, "Stock", "Acme", "alice", expected_bom_plan=plan)

        assert blank_store.stock_at("COMP", "Stock", "LOT-A") == 0
        assert blank_store.stock_at("COMP", "Stock", "LOT-B") == 1

    def test_bom_shipping_requires_a_reviewed_plan(self, blank_store):
        build_nested_bom(blank_store)
        blank_store.receive("SCREW-001", 20, "Stock", "LOT-1", "setup")
        blank_store.receive("NUT-001", 20, "Stock", "LOT-1", "setup")

        with pytest.raises(ValueError, match="Review the BOM lot allocation"):
            blank_store.ship("KIT-001", 1, "Stock", "Acme", "alice")

        assert blank_store.shipments == []
