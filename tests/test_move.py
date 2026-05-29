"""
test_move.py — Tests for the move workflow.

Covers:
  - InventoryStore.move (balance updates at both ends, two transaction rows,
    guards against bad input and insufficient stock)

Learning note — two-sided operations
--------------------------------------
Moving stock is an atomic two-step operation: the source balance decreases
AND the destination balance increases.  A correct move must satisfy BOTH
sides.  We test each side in its own dedicated test function so a failure
tells you exactly which half broke.

Learning note — testing transaction pairs
------------------------------------------
move() always creates exactly two transaction rows:
  [0]  MOVE_IN  (prepended last → newest)
  [1]  MOVE_OUT (prepended first → older)

Tests below use index [0] and [1] to access them.  If the implementation
ever changes the insertion order, these tests will fail and catch the change.
"""

import pytest


# ===========================================================================
# move — happy path
# ===========================================================================

class TestMoveHappyPath:

    def test_source_balance_decreases(self, part_in_store):
        # Arrange: TEST-001 has 10 in Stock
        # Act: move 4 from Stock → Shipping Bench
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")
        # Assert
        assert part_in_store.stock_at("TEST-001", "Stock") == 6

    def test_destination_balance_increases(self, part_in_store):
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert part_in_store.stock_at("TEST-001", "Shipping Bench") == 4

    def test_total_stock_is_unchanged_after_move(self, part_in_store):
        # Moving does not create or destroy units — total must stay the same
        before = part_in_store.total_stock("TEST-001")

        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert part_in_store.total_stock("TEST-001") == before

    def test_two_transactions_are_created(self, part_in_store):
        # part_in_store already has 1 RECEIVE transaction from conftest setup
        tx_count_before = len(part_in_store.transactions)

        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert len(part_in_store.transactions) == tx_count_before + 2

    def test_move_in_transaction_is_most_recent(self, part_in_store):
        # MOVE_IN is inserted last (second insert) so it ends up at [0]
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert part_in_store.transactions[0].tx_type == "MOVE_IN"

    def test_move_out_transaction_is_second(self, part_in_store):
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert part_in_store.transactions[1].tx_type == "MOVE_OUT"

    def test_move_in_has_positive_quantity(self, part_in_store):
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert part_in_store.transactions[0].quantity_change == 4

    def test_move_out_has_negative_quantity(self, part_in_store):
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert part_in_store.transactions[1].quantity_change == -4

    def test_both_transactions_record_source_and_destination(self, part_in_store):
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        move_in = part_in_store.transactions[0]
        move_out = part_in_store.transactions[1]

        # Both rows store both locations so the log is self-contained
        assert move_in.location_from == "Stock"
        assert move_in.location_to == "Shipping Bench"
        assert move_out.location_from == "Stock"
        assert move_out.location_to == "Shipping Bench"

    def test_transactions_record_operator(self, part_in_store):
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol")

        assert part_in_store.transactions[0].operator == "carol"
        assert part_in_store.transactions[1].operator == "carol"

    def test_transactions_record_reference(self, part_in_store):
        part_in_store.move("TEST-001", 4, "Stock", "Shipping Bench", "carol",
                           reference="WO-007")

        assert part_in_store.transactions[0].reference == "WO-007"
        assert part_in_store.transactions[1].reference == "WO-007"

    def test_move_entire_available_quantity_succeeds(self, part_in_store):
        # Moving exactly the available amount (10) should be allowed
        part_in_store.move("TEST-001", 10, "Stock", "Shipping Bench", "carol")

        assert part_in_store.stock_at("TEST-001", "Stock") == 0
        assert part_in_store.stock_at("TEST-001", "Shipping Bench") == 10


# ===========================================================================
# move — validation / guards
# ===========================================================================

class TestMoveValidation:

    def test_same_source_and_destination_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Source and destination cannot match"):
            part_in_store.move("TEST-001", 1, "Stock", "Stock", "carol")

    def test_insufficient_source_stock_raises(self, part_in_store):
        # Only 10 in Stock; request 11
        with pytest.raises(ValueError, match="Not enough stock"):
            part_in_store.move("TEST-001", 11, "Stock", "Shipping Bench", "carol")

    def test_insufficient_stock_does_not_change_either_balance(self, part_in_store):
        try:
            part_in_store.move("TEST-001", 99, "Stock", "Shipping Bench", "carol")
        except ValueError:
            pass

        assert part_in_store.stock_at("TEST-001", "Stock") == 10
        assert part_in_store.stock_at("TEST-001", "Shipping Bench") == 0

    def test_insufficient_stock_does_not_create_transactions(self, part_in_store):
        tx_count_before = len(part_in_store.transactions)

        try:
            part_in_store.move("TEST-001", 99, "Stock", "Shipping Bench", "carol")
        except ValueError:
            pass

        assert len(part_in_store.transactions) == tx_count_before

    def test_invalid_source_location_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Invalid location"):
            part_in_store.move("TEST-001", 1, "Narnia", "Stock", "carol")

    def test_invalid_destination_location_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Invalid destination location"):
            part_in_store.move("TEST-001", 1, "Stock", "Narnia", "carol")

    def test_unknown_part_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Part not found"):
            part_in_store.move("GHOST-000", 1, "Stock", "Shipping Bench", "carol")

    @pytest.mark.parametrize("qty", [0, -1])
    def test_non_positive_quantity_raises(self, part_in_store, qty):
        with pytest.raises(ValueError, match="Quantity must be greater than zero"):
            part_in_store.move("TEST-001", qty, "Stock", "Shipping Bench", "carol")
