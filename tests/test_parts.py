"""
test_parts.py — Tests for part creation and stock query helpers.

Covers:
  - InventoryStore.add_part      (happy path + validation)
  - InventoryStore.total_stock   (sum across all locations)
  - InventoryStore.stock_at      (single-location query)
  - InventoryStore.low_stock     (alert logic)

Learning note — AAA pattern
----------------------------
Every test in this file follows the Arrange / Act / Assert pattern:

  Arrange  — set up the state the test needs (add a part, receive stock, …)
  Act      — call the single thing being tested
  Assert   — verify the outcome

Keeping tests to one logical assertion per test makes failures easy to
diagnose: you know exactly which behaviour broke.

Learning note — pytest.raises
------------------------------
Use `with pytest.raises(ExceptionType, match="text"):` to assert that a call
raises a specific exception AND that the error message contains "text".
The `match` argument is a regex pattern searched inside str(exception), so
plain English phrases work fine — you don't need to match the whole message.

Learning note — pytest.mark.parametrize
-----------------------------------------
When you have many inputs that should all trigger the same behaviour (e.g.,
many invalid inputs that should all raise ValueError), parametrize lets you
write one test function and supply a list of (input, expected_output) rows.
This avoids copy-pasting near-identical tests and makes the test table easy
to extend later.
"""

import pytest


# ===========================================================================
# add_part — happy path
# ===========================================================================

class TestAddPartHappyPath:
    """Tests that confirm add_part works correctly for valid inputs."""

    def test_part_is_stored_in_parts_dict(self, blank_store):
        # Arrange: store is empty
        # Act
        blank_store.add_part("ABC-1", "Widget A")
        # Assert
        assert "ABC-1" in blank_store.parts

    def test_part_number_is_normalised_to_uppercase(self, blank_store):
        # lowercase input should be stored as uppercase
        blank_store.add_part("abc-1", "Widget A")

        assert "ABC-1" in blank_store.parts
        assert "abc-1" not in blank_store.parts  # original casing NOT stored

    def test_part_number_strips_surrounding_whitespace(self, blank_store):
        blank_store.add_part("  ABC-1  ", "Widget A")

        assert "ABC-1" in blank_store.parts

    def test_description_is_stripped_of_whitespace(self, blank_store):
        blank_store.add_part("ABC-1", "  Widget A  ")

        assert blank_store.parts["ABC-1"].description == "Widget A"

    def test_default_minimum_quantity_is_zero(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")

        assert blank_store.parts["ABC-1"].minimum_quantity == 0

    def test_custom_minimum_quantity_is_stored(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A", minimum_quantity=5)

        assert blank_store.parts["ABC-1"].minimum_quantity == 5

    def test_balance_initialised_to_zero_for_every_location(self, blank_store):
        # When a part is added, it should start with 0 stock in every location.
        blank_store.add_part("ABC-1", "Widget A")

        for location in blank_store.locations:
            assert blank_store.stock_at("ABC-1", location) == 0, (
                f"Expected 0 at {location!r}, but got {blank_store.stock_at('ABC-1', location)}"
            )

    def test_part_is_active_by_default(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")

        assert blank_store.parts["ABC-1"].active is True


# ===========================================================================
# add_part — validation
# ===========================================================================

class TestAddPartValidation:
    """
    Tests that confirm add_part rejects invalid inputs.

    The parametrize block below is a table of (inputs → expected error text).
    Adding a new invalid case is as simple as appending a row to the list.
    """

    @pytest.mark.parametrize("part_number, description, minimum_quantity, location, expected_msg", [
        # --- part_number ---
        ("",      "Widget", 0, "Stock", "Part number required"),
        ("   ",   "Widget", 0, "Stock", "Part number required"),   # whitespace-only

        # --- description ---
        ("P-1", "",        0, "Stock", "Description required"),
        ("P-1", "   ",     0, "Stock", "Description required"),    # whitespace-only

        # --- minimum_quantity ---
        ("P-1", "Widget", -1, "Stock", "Minimum quantity cannot be negative"),

        # --- location ---
        ("P-1", "Widget",  0, "Nowhere", "Invalid location"),
        ("P-1", "Widget",  0, "",        "Invalid location"),
    ])
    def test_invalid_input_raises_value_error(
        self,
        blank_store,
        part_number,
        description,
        minimum_quantity,
        location,
        expected_msg,
    ):
        with pytest.raises(ValueError, match=expected_msg):
            blank_store.add_part(part_number, description, minimum_quantity, location)

    def test_duplicate_part_number_raises(self, blank_store):
        # Arrange: add the part once successfully
        blank_store.add_part("ABC-1", "Widget A")

        # Act + Assert: adding the same number again must fail
        with pytest.raises(ValueError, match="Part already exists"):
            blank_store.add_part("ABC-1", "Different Description")

    def test_duplicate_detection_is_case_insensitive(self, blank_store):
        # 'abc-1' normalises to 'ABC-1', which collides with an existing entry
        blank_store.add_part("ABC-1", "Widget A")

        with pytest.raises(ValueError, match="Part already exists"):
            blank_store.add_part("abc-1", "Widget A")


# ===========================================================================
# stock_at and total_stock
# ===========================================================================

class TestStockQueries:
    """Tests for the two balance query helpers."""

    def test_stock_at_returns_quantity_for_known_location(self, blank_store):
        # Arrange
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 7, "Stock", "tester")

        # Act + Assert
        assert blank_store.stock_at("ABC-1", "Stock") == 7

    def test_stock_at_returns_zero_for_location_with_no_stock(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        # Nothing received at Receiving
        assert blank_store.stock_at("ABC-1", "Receiving") == 0

    def test_stock_at_returns_zero_for_unknown_part(self, blank_store):
        # No error should be raised for a completely unknown part
        assert blank_store.stock_at("GHOST-000", "Stock") == 0

    def test_total_stock_sums_all_locations(self, blank_store):
        # Arrange: spread stock across two locations
        blank_store.add_part("ABC-1", "Widget A")
        blank_store.receive("ABC-1", 5, "Stock", "tester")
        blank_store.receive("ABC-1", 3, "Receiving", "tester")

        # Act + Assert: 5 + 3 = 8
        assert blank_store.total_stock("ABC-1") == 8

    def test_total_stock_returns_zero_for_new_part(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")

        assert blank_store.total_stock("ABC-1") == 0

    def test_total_stock_returns_zero_for_unknown_part(self, blank_store):
        assert blank_store.total_stock("GHOST-000") == 0


# ===========================================================================
# low_stock
# ===========================================================================

class TestLowStock:
    """
    Tests for the low-stock alert logic.

    A part is considered low stock when:
      total_stock(part) <= part.minimum_quantity  AND  minimum_quantity > 0
    """

    def test_part_below_minimum_is_returned(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A", minimum_quantity=5)
        blank_store.receive("ABC-1", 3, "Stock", "tester")  # 3 < 5 → low

        low = blank_store.low_stock()

        assert any(p.part_number == "ABC-1" for p in low)

    def test_part_exactly_at_minimum_is_returned(self, blank_store):
        # At minimum is still considered low — it needs restocking
        blank_store.add_part("ABC-1", "Widget A", minimum_quantity=5)
        blank_store.receive("ABC-1", 5, "Stock", "tester")  # 5 == 5 → low

        low = blank_store.low_stock()

        assert any(p.part_number == "ABC-1" for p in low)

    def test_part_above_minimum_is_not_returned(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A", minimum_quantity=5)
        blank_store.receive("ABC-1", 10, "Stock", "tester")  # 10 > 5 → ok

        low = blank_store.low_stock()

        assert not any(p.part_number == "ABC-1" for p in low)

    def test_part_with_zero_minimum_is_excluded(self, blank_store):
        # minimum_quantity=0 means "no minimum set" — never alert for these
        blank_store.add_part("ABC-1", "Widget A", minimum_quantity=0)
        # Even with zero stock it should NOT appear

        low = blank_store.low_stock()

        assert not any(p.part_number == "ABC-1" for p in low)

    def test_low_stock_returns_empty_list_when_all_ok(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A", minimum_quantity=2)
        blank_store.receive("ABC-1", 10, "Stock", "tester")

        assert blank_store.low_stock() == []

    def test_only_low_parts_appear_when_mixed(self, blank_store):
        # Two parts: one below minimum, one above
        blank_store.add_part("LOW-1", "Low Part", minimum_quantity=5)
        blank_store.receive("LOW-1", 2, "Stock", "tester")    # low

        blank_store.add_part("OK-1", "OK Part", minimum_quantity=5)
        blank_store.receive("OK-1", 10, "Stock", "tester")    # fine

        low_numbers = {p.part_number for p in blank_store.low_stock()}

        assert "LOW-1" in low_numbers
        assert "OK-1" not in low_numbers
