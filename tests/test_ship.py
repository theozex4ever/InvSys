"""
test_ship.py — Tests for the ship workflow.

Covers:
  - InventoryStore.ship (balance decrease, shipment record, transaction,
    shipment number format, guards against insufficient stock)

Learning note — multiple assertions in one test
-------------------------------------------------
For some tests (e.g. test_shipment_record_fields) it makes sense to assert
multiple related fields of the same object in one test function.  This is
acceptable when all assertions describe a single logical fact: "the shipment
record was saved with the correct data."  It becomes a problem when each
assertion tests a different concern — in that case, split them.

Learning note — using part_in_store
-------------------------------------
ship requires an existing part with available stock.  Rather than repeating
`add_part → receive` in every test, we use the `part_in_store` fixture from
conftest.py which provides:
    TEST-001  "Test Widget"  min_qty=3  Stock ×10
"""

import re
import pytest


# ===========================================================================
# ship — happy path
# ===========================================================================

class TestShipHappyPath:

    def test_balance_decreases_by_shipped_quantity(self, part_in_store):
        # Arrange: part_in_store has 10 units in Stock
        # Act
        part_in_store.ship("TEST-001", 4, "Stock", "Acme Corp", "bob", "LOT-1")
        # Assert
        assert part_in_store.stock_at("TEST-001", "Stock") == 6

    def test_ship_returns_a_shipment_number(self, part_in_store):
        result = part_in_store.ship("TEST-001", 1, "Stock", "Acme Corp", "bob", "LOT-1")

        assert result is not None
        assert isinstance(result, str)

    def test_shipment_number_matches_expected_format(self, part_in_store):
        # Expected format: SHP-YYYYMMDD-0001
        shipment_number = part_in_store.ship("TEST-001", 1, "Stock", "Acme Corp", "bob", "LOT-1")

        # re.match checks from the start of the string
        assert re.match(r"SHP-\d{8}-\d{4}$", shipment_number), (
            f"Unexpected shipment number format: {shipment_number!r}"
        )

    def test_shipment_counter_increments_each_call(self, part_in_store):
        sn1 = part_in_store.ship("TEST-001", 1, "Stock", "Acme Corp", "bob", "LOT-1")
        sn2 = part_in_store.ship("TEST-001", 1, "Stock", "Acme Corp", "bob", "LOT-1")

        # The last four digits are the sequential counter
        counter1 = int(sn1.split("-")[-1])
        counter2 = int(sn2.split("-")[-1])
        assert counter2 == counter1 + 1

    def test_shipment_record_is_created(self, part_in_store):
        part_in_store.ship("TEST-001", 3, "Stock", "Acme Corp", "bob", "LOT-1")

        assert len(part_in_store.shipments) == 1

    def test_shipment_record_fields(self, part_in_store):
        # All optional fields are supplied here so we can verify full storage.
        sn = part_in_store.ship(
            "TEST-001", 3, "Stock", "Acme Corp", "bob", "LOT-1",
            carrier="FedEx", tracking="1Z999"
        )
        shipment = part_in_store.shipments[0]

        assert shipment.shipment_number == sn
        assert shipment.part_number == "TEST-001"
        assert shipment.quantity == 3
        assert shipment.recipient == "Acme Corp"
        assert shipment.carrier == "FedEx"
        assert shipment.tracking_number == "1Z999"

    def test_ship_creates_a_ship_transaction(self, part_in_store):
        part_in_store.ship("TEST-001", 3, "Stock", "Acme Corp", "bob", "LOT-1")

        # The seed receive is at index [1]; our SHIP transaction is at [0]
        ship_tx = part_in_store.transactions[0]
        assert ship_tx.tx_type == "SHIP"

    def test_ship_transaction_has_negative_quantity(self, part_in_store):
        # Shipping reduces stock → the transaction records a negative change
        part_in_store.ship("TEST-001", 4, "Stock", "Acme Corp", "bob", "LOT-1")

        ship_tx = part_in_store.transactions[0]
        assert ship_tx.quantity_change == -4

    def test_ship_transaction_records_operator(self, part_in_store):
        part_in_store.ship("TEST-001", 1, "Stock", "Acme Corp", "bob", "LOT-1")

        ship_tx = part_in_store.transactions[0]
        assert ship_tx.operator == "bob"

    def test_recipient_whitespace_is_stripped(self, part_in_store):
        part_in_store.ship("TEST-001", 1, "Stock", "  Acme Corp  ", "bob", "LOT-1")

        assert part_in_store.shipments[0].recipient == "Acme Corp"

    def test_most_recent_shipment_is_first(self, part_in_store):
        part_in_store.ship("TEST-001", 1, "Stock", "First", "bob", "LOT-1")
        part_in_store.ship("TEST-001", 1, "Stock", "Second", "bob", "LOT-1")

        assert part_in_store.shipments[0].recipient == "Second"
        assert part_in_store.shipments[1].recipient == "First"


# ===========================================================================
# ship — validation / guards
# ===========================================================================

class TestShipValidation:

    def test_insufficient_stock_raises_value_error(self, part_in_store):
        # part_in_store has 10 in Stock; request 11
        with pytest.raises(ValueError, match="Not enough stock"):
            part_in_store.ship("TEST-001", 11, "Stock", "Acme Corp", "bob", "LOT-1")

    def test_error_message_includes_available_and_requested(self, part_in_store):
        # The error should tell the operator exactly what went wrong
        with pytest.raises(ValueError, match="Available: 10") as exc_info:
            part_in_store.ship("TEST-001", 99, "Stock", "Acme Corp", "bob", "LOT-1")
        assert "requested: 99" in str(exc_info.value)

    def test_insufficient_stock_does_not_change_balance(self, part_in_store):
        # When ship fails the balance must be exactly as it was before
        try:
            part_in_store.ship("TEST-001", 99, "Stock", "Acme Corp", "bob", "LOT-1")
        except ValueError:
            pass

        assert part_in_store.stock_at("TEST-001", "Stock") == 10

    def test_insufficient_stock_does_not_create_shipment_record(self, part_in_store):
        try:
            part_in_store.ship("TEST-001", 99, "Stock", "Acme Corp", "bob", "LOT-1")
        except ValueError:
            pass

        assert len(part_in_store.shipments) == 0

    def test_empty_recipient_raises_value_error(self, part_in_store):
        with pytest.raises(ValueError, match="Recipient required"):
            part_in_store.ship("TEST-001", 1, "Stock", "", "bob", "LOT-1")

    def test_whitespace_only_recipient_raises_value_error(self, part_in_store):
        with pytest.raises(ValueError, match="Recipient required"):
            part_in_store.ship("TEST-001", 1, "Stock", "   ", "bob", "LOT-1")

    def test_unknown_part_raises_value_error(self, part_in_store):
        with pytest.raises(ValueError, match="Part not found"):
            part_in_store.ship("GHOST-000", 1, "Stock", "Acme Corp", "bob", "LOT-1")

    def test_invalid_location_raises_value_error(self, part_in_store):
        with pytest.raises(ValueError, match="Invalid location"):
            part_in_store.ship("TEST-001", 1, "Narnia", "Acme Corp", "bob", "LOT-1")

    @pytest.mark.parametrize("qty", [0, -1, -10])
    def test_non_positive_quantity_raises_value_error(self, part_in_store, qty):
        with pytest.raises(ValueError, match="Quantity must be greater than zero"):
            part_in_store.ship("TEST-001", qty, "Stock", "Acme Corp", "bob", "LOT-1")

    def test_exactly_available_quantity_succeeds(self, part_in_store):
        # Shipping the exact available quantity (10) should be allowed
        sn = part_in_store.ship("TEST-001", 10, "Stock", "Acme Corp", "bob", "LOT-1")

        assert part_in_store.stock_at("TEST-001", "Stock") == 0
        assert sn is not None
