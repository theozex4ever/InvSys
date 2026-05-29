"""
test_adjust.py — Tests for the count-correction (adjust) workflow.

Covers:
  - InventoryStore.adjust (balance overwrite, diff return value,
    COUNT_CORRECTION transaction, validation)

Key behaviour
-------------
adjust() is NOT a relative change ("add 3").  It is an absolute overwrite:
"the correct count IS 8."  The store calculates the difference and records it
as the transaction quantity_change so the audit trail shows what changed.

adjust() returns the signed difference so the caller can display it:
  "Count corrected. Difference: -2."
"""

import pytest


# ===========================================================================
# adjust — happy path
# ===========================================================================

class TestAdjustHappyPath:

    def test_balance_is_set_to_new_count(self, part_in_store):
        # Arrange: part_in_store has 10 in Stock
        # Act: physical count shows 8
        part_in_store.adjust("TEST-001", "Stock", 8, "dave", "Physical count")
        # Assert: system balance now equals the counted value
        assert part_in_store.stock_at("TEST-001", "Stock") == 8

    def test_adjust_up_sets_correct_balance(self, part_in_store):
        # Count shows MORE than the system — also valid
        part_in_store.adjust("TEST-001", "Stock", 15, "dave", "Found extra units")

        assert part_in_store.stock_at("TEST-001", "Stock") == 15

    def test_adjust_to_zero_is_allowed(self, part_in_store):
        part_in_store.adjust("TEST-001", "Stock", 0, "dave", "Bin is empty")

        assert part_in_store.stock_at("TEST-001", "Stock") == 0

    def test_returns_negative_diff_when_counting_down(self, part_in_store):
        # Started at 10, counted 8 → diff should be -2
        diff = part_in_store.adjust("TEST-001", "Stock", 8, "dave", "Physical count")

        assert diff == -2

    def test_returns_positive_diff_when_counting_up(self, part_in_store):
        # Started at 10, counted 14 → diff should be +4
        diff = part_in_store.adjust("TEST-001", "Stock", 14, "dave", "Re-count found extras")

        assert diff == 4

    def test_returns_zero_diff_when_count_matches(self, part_in_store):
        # Count matches system — no change, but transaction still recorded
        diff = part_in_store.adjust("TEST-001", "Stock", 10, "dave", "Spot check")

        assert diff == 0

    def test_creates_count_correction_transaction(self, part_in_store):
        part_in_store.adjust("TEST-001", "Stock", 8, "dave", "Physical count")

        tx = part_in_store.transactions[0]
        assert tx.tx_type == "COUNT_CORRECTION"

    def test_transaction_quantity_change_matches_diff(self, part_in_store):
        # The transaction should record the diff, not the absolute new count
        part_in_store.adjust("TEST-001", "Stock", 8, "dave", "Physical count")

        tx = part_in_store.transactions[0]
        assert tx.quantity_change == -2  # 8 - 10

    def test_transaction_records_reason_as_reference(self, part_in_store):
        part_in_store.adjust("TEST-001", "Stock", 8, "dave", "Cycle count Q2")

        tx = part_in_store.transactions[0]
        assert tx.reference == "Cycle count Q2"

    def test_transaction_records_operator(self, part_in_store):
        part_in_store.adjust("TEST-001", "Stock", 8, "dave", "Physical count")

        tx = part_in_store.transactions[0]
        assert tx.operator == "dave"

    def test_transaction_records_location(self, part_in_store):
        # Both location_from and location_to are the adjusted location
        part_in_store.adjust("TEST-001", "Stock", 8, "dave", "Physical count")

        tx = part_in_store.transactions[0]
        assert tx.location_from == "Stock"
        assert tx.location_to == "Stock"

    def test_adjust_only_affects_specified_location(self, part_in_store):
        # Receive some stock at a second location first
        part_in_store.receive("TEST-001", 5, "Receiving", "tester")

        # Adjust Stock only
        part_in_store.adjust("TEST-001", "Stock", 7, "dave", "Spot check")

        assert part_in_store.stock_at("TEST-001", "Stock") == 7
        assert part_in_store.stock_at("TEST-001", "Receiving") == 5  # untouched


# ===========================================================================
# adjust — validation / guards
# ===========================================================================

class TestAdjustValidation:

    def test_negative_new_count_raises(self, part_in_store):
        with pytest.raises(ValueError, match="New count cannot be negative"):
            part_in_store.adjust("TEST-001", "Stock", -1, "dave", "Error")

    def test_empty_reason_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Reason required"):
            part_in_store.adjust("TEST-001", "Stock", 8, "dave", "")

    def test_whitespace_only_reason_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Reason required"):
            part_in_store.adjust("TEST-001", "Stock", 8, "dave", "   ")

    def test_unknown_part_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Part not found"):
            part_in_store.adjust("GHOST-000", "Stock", 5, "dave", "Spot check")

    def test_invalid_location_raises(self, part_in_store):
        with pytest.raises(ValueError, match="Invalid location"):
            part_in_store.adjust("TEST-001", "Narnia", 5, "dave", "Spot check")

    def test_failed_adjust_does_not_change_balance(self, part_in_store):
        try:
            part_in_store.adjust("TEST-001", "Stock", -1, "dave", "Error")
        except ValueError:
            pass

        assert part_in_store.stock_at("TEST-001", "Stock") == 10

    def test_failed_adjust_does_not_create_transaction(self, part_in_store):
        tx_count_before = len(part_in_store.transactions)

        try:
            part_in_store.adjust("TEST-001", "Stock", -1, "dave", "Error")
        except ValueError:
            pass

        assert len(part_in_store.transactions) == tx_count_before

    @pytest.mark.parametrize("bad_reason", ["", "   ", "\t"])
    def test_various_blank_reasons_are_rejected(self, part_in_store, bad_reason):
        with pytest.raises(ValueError, match="Reason required"):
            part_in_store.adjust("TEST-001", "Stock", 5, "dave", bad_reason)
