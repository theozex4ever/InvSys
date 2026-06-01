"""
test_receive.py — Tests for the receive workflow.

Covers:
  - InventoryStore.receive (balance increase, transaction creation, validation)

Learning note — testing side effects
--------------------------------------
`receive` does two things at once: it updates a balance AND appends a
transaction record.  A good test verifies both effects independently.
This is called testing side effects — the operation changes state in multiple
places and we must assert on each one.

The most recently added transaction is always at index [0] because
`transactions.insert(0, ...)` prepends.  Tests here rely on that invariant.

Learning note — choosing between blank_store and part_in_store
---------------------------------------------------------------
receive tests use `blank_store` with explicit setup (add_part first) rather
than `part_in_store`.  This makes the preconditions obvious at the top of
each test.  For tests that only care about the outcome and not the setup,
`part_in_store` (defined in conftest.py) is more concise.
"""

import pytest


# ===========================================================================
# receive — happy path
# ===========================================================================

class TestReceiveHappyPath:

    def test_balance_increases_by_received_quantity(self, blank_store):
        # Arrange
        blank_store.add_part("ABC-1", "Widget A")

        # Act
        blank_store.receive("ABC-1", 10, "Stock", "LOT-1", "alice")

        # Assert
        assert blank_store.stock_at("ABC-1", "Stock") == 10

    def test_receiving_twice_accumulates_quantity(self, blank_store):
        # Receiving is additive — each call adds to the existing balance.
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "alice")

        blank_store.receive("ABC-1", 3, "Stock", "LOT-1", "alice")

        assert blank_store.stock_at("ABC-1", "Stock") == 8

    def test_receive_into_different_locations_are_independent(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 4, "Receiving", "LOT-1", "alice")
        blank_store.receive("ABC-1", 6, "Stock", "LOT-1", "alice")

        assert blank_store.stock_at("ABC-1", "Receiving") == 4
        assert blank_store.stock_at("ABC-1", "Stock") == 6

    def test_receive_creates_a_transaction_record(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 10, "Stock", "LOT-1", "alice")

        # A transaction should now exist
        assert len(blank_store.transactions) == 1

    def test_transaction_type_is_RECEIVE(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 10, "Stock", "LOT-1", "alice")

        tx = blank_store.transactions[0]
        assert tx.tx_type == "RECEIVE"

    def test_transaction_records_correct_quantity_change(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 10, "Stock", "LOT-1", "alice")

        tx = blank_store.transactions[0]
        assert tx.quantity_change == 10  # positive for receiving

    def test_transaction_records_destination_location(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 10, "Receiving", "LOT-1", "alice")

        tx = blank_store.transactions[0]
        assert tx.location_to == "Receiving"

    def test_transaction_records_operator_name(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 10, "Stock", "LOT-1", "alice")

        tx = blank_store.transactions[0]
        assert tx.operator == "alice"

    def test_transaction_records_optional_reference(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 10, "Stock", "LOT-1", "alice", reference="PO-001")

        tx = blank_store.transactions[0]
        assert tx.reference == "PO-001"

    def test_transaction_records_optional_notes(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 10, "Stock", "LOT-1", "alice", notes="Urgent order")

        tx = blank_store.transactions[0]
        assert tx.notes == "Urgent order"

    def test_most_recent_transaction_is_first(self, blank_store):
        # transactions are prepended, so [0] is always the latest
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "alice", reference="first")
        blank_store.receive("ABC-1", 3, "Stock", "LOT-1", "alice", reference="second")

        assert blank_store.transactions[0].reference == "second"
        assert blank_store.transactions[1].reference == "first"


# ===========================================================================
# receive — validation
# ===========================================================================

class TestReceiveValidation:
    """
    Tests that confirm receive rejects inputs that would corrupt inventory.

    These tests use the same parametrize pattern shown in test_parts.py to
    keep the invalid-input table compact.
    """

    def test_unknown_part_raises_value_error(self, blank_store):
        with pytest.raises(ValueError, match="Part not found"):
            blank_store.receive("GHOST-000", 1, "Stock", "LOT-1", "alice")

    def test_invalid_location_raises_value_error(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")

        with pytest.raises(ValueError, match="Invalid location"):
            blank_store.receive("ABC-1", 1, "Narnia", "LOT-1", "alice")

    @pytest.mark.parametrize("qty, label", [
        (0,  "zero"),
        (-1, "negative"),
        (-99, "large negative"),
    ])
    def test_non_positive_quantity_raises_value_error(self, blank_store, qty, label):
        blank_store.add_part("ABC-1", "Widget A")

        with pytest.raises(ValueError, match="Quantity must be greater than zero"):
            blank_store.receive("ABC-1", qty, "Stock", "LOT-1", "alice")

    def test_failed_receive_does_not_change_balance(self, blank_store):
        # If the call raises, the balance must be unchanged.
        blank_store.add_part("ABC-1", "Widget A")

        try:
            blank_store.receive("ABC-1", 0, "Stock", "LOT-1", "alice")
        except ValueError:
            pass

        assert blank_store.stock_at("ABC-1", "Stock") == 0

    def test_failed_receive_does_not_create_transaction(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")

        try:
            blank_store.receive("ABC-1", -5, "Stock", "LOT-1", "alice")
        except ValueError:
            pass

        assert len(blank_store.transactions) == 0
