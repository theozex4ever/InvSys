"""
test_notifications.py — Tests for the subscriber / notify pattern.

Covers:
  - InventoryStore.subscribe  (registers a callback)
  - InventoryStore.notify     (calls all registered callbacks)
  - notify=False flag on add_part and receive

Why this matters
-----------------
The UI views refresh themselves by subscribing to the store.  If notify stops
working, every screen silently shows stale data.  These tests guard that
contract.

Learning note — using a simple counter instead of a mock
---------------------------------------------------------
We could use `unittest.mock.MagicMock()` to track calls, but a plain integer
counter inside a list (a mutable default — a classic Python trick to allow
mutation inside a nested function) keeps the code dependency-free and easy to
read.  Both approaches are valid; the important thing is that the test is
explicit about how many times the callback was called.

    call_count = [0]

    def on_change():
        call_count[0] += 1

Learning note — testing callbacks
-----------------------------------
A callback test pattern:
  1. Create a counter that the callback increments.
  2. Subscribe the callback to the store.
  3. Perform the action.
  4. Assert the counter was incremented the expected number of times.

This is simpler than checking WHAT the callback was called with — we just
need to know that it WAS called.
"""

import pytest


# ---------------------------------------------------------------------------
# Helper used throughout this module
# ---------------------------------------------------------------------------

def make_counter():
    """
    Returns (counter_list, callback_fn).

    counter_list[0] holds the call count.  The callback increments it each
    time it is called.  We use a list because Python closures cannot rebind a
    plain integer variable in the outer scope, but they CAN mutate a list.
    """
    count = [0]

    def callback():
        count[0] += 1

    return count, callback


# ===========================================================================
# subscribe + notify basics
# ===========================================================================

class TestSubscribeAndNotify:

    def test_subscriber_is_called_after_add_part(self, blank_store):
        count, cb = make_counter()
        blank_store.subscribe(cb)

        blank_store.add_part("ABC-1", "Widget A")

        assert count[0] == 1

    def test_subscriber_is_called_after_receive(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        count, cb = make_counter()
        blank_store.subscribe(cb)

        blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "alice")

        assert count[0] == 1

    def test_subscriber_is_called_after_ship(self, part_in_store):
        count, cb = make_counter()
        part_in_store.subscribe(cb)

        part_in_store.ship("TEST-001", 1, "Stock", "Acme Corp", "bob", "LOT-1")

        assert count[0] == 1

    def test_subscriber_is_called_after_move(self, part_in_store):
        count, cb = make_counter()
        part_in_store.subscribe(cb)

        part_in_store.move("TEST-001", 1, "Stock", "Shipping Bench", "LOT-1", "carol")

        assert count[0] == 1

    def test_subscriber_is_called_after_adjust(self, part_in_store):
        count, cb = make_counter()
        part_in_store.subscribe(cb)

        part_in_store.adjust("TEST-001", "Stock", "LOT-1", 7, "dave", "Spot check")

        assert count[0] == 1

    def test_subscriber_called_once_per_mutating_operation(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        count, cb = make_counter()
        blank_store.subscribe(cb)

        # Three separate receives → three calls
        blank_store.receive("ABC-1", 1, "Stock", "LOT-1", "alice")
        blank_store.receive("ABC-1", 2, "Stock", "LOT-1", "alice")
        blank_store.receive("ABC-1", 3, "Stock", "LOT-1", "alice")

        assert count[0] == 3


# ===========================================================================
# multiple subscribers
# ===========================================================================

class TestMultipleSubscribers:

    def test_all_subscribers_are_called(self, blank_store):
        count_a, cb_a = make_counter()
        count_b, cb_b = make_counter()
        blank_store.subscribe(cb_a)
        blank_store.subscribe(cb_b)

        blank_store.add_part("ABC-1", "Widget A")

        assert count_a[0] == 1
        assert count_b[0] == 1

    def test_each_subscriber_receives_same_number_of_calls(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A")
        count_a, cb_a = make_counter()
        count_b, cb_b = make_counter()
        blank_store.subscribe(cb_a)
        blank_store.subscribe(cb_b)

        blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "alice")
        blank_store.receive("ABC-1", 3, "Stock", "LOT-1", "alice")

        assert count_a[0] == count_b[0] == 2

    def test_subscribing_same_callback_twice_calls_it_twice(self, blank_store):
        # The store does not de-duplicate subscribers.  This is expected
        # behaviour for the current MVP.
        count, cb = make_counter()
        blank_store.subscribe(cb)
        blank_store.subscribe(cb)  # same function registered twice

        blank_store.add_part("ABC-1", "Widget A")

        assert count[0] == 2


# ===========================================================================
# notify=False flag
# ===========================================================================

class TestNotifyFalseFlag:
    """
    add_part and receive accept notify=False so the seed() method can
    populate demo data without triggering UI refreshes before the window
    is ready.
    """

    def test_add_part_with_notify_false_does_not_call_subscriber(self, blank_store):
        count, cb = make_counter()
        blank_store.subscribe(cb)

        blank_store.add_part("ABC-1", "Widget A", notify=False)

        assert count[0] == 0, "Subscriber should NOT be called when notify=False"

    def test_receive_with_notify_false_does_not_call_subscriber(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A", notify=False)
        count, cb = make_counter()
        blank_store.subscribe(cb)

        blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "alice", notify=False)

        assert count[0] == 0, "Subscriber should NOT be called when notify=False"

    def test_notify_false_still_updates_balance(self, blank_store):
        # The flag only suppresses the callback — the data change must still happen
        blank_store.add_part("ABC-1", "Widget A", notify=False)
        blank_store.receive("ABC-1", 7, "Stock", "LOT-1", "alice", notify=False)

        assert blank_store.stock_at("ABC-1", "Stock") == 7

    def test_notify_false_still_creates_transaction(self, blank_store):
        blank_store.add_part("ABC-1", "Widget A", notify=False)
        blank_store.receive("ABC-1", 7, "Stock", "LOT-1", "alice", notify=False)

        assert len(blank_store.transactions) == 1
        assert blank_store.transactions[0].tx_type == "RECEIVE"

    def test_subsequent_normal_call_still_notifies(self, blank_store):
        # After a silent call, the next normal call should notify as usual
        blank_store.add_part("ABC-1", "Widget A", notify=False)
        count, cb = make_counter()
        blank_store.subscribe(cb)

        blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "alice")  # notify=True (default)

        assert count[0] == 1
