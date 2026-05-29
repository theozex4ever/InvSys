"""
conftest.py — Shared pytest fixtures for the Inventory Control test suite.

What is conftest.py?
--------------------
pytest automatically loads this file before running any test in the same
directory (or any subdirectory).  Fixtures defined here are available to
every test file without needing an explicit import — pytest injects them by
name.  Think of it as shared setup that all tests can opt into.

What is a fixture?
------------------
A fixture is a function decorated with @pytest.fixture that provides a
ready-made object (or state) to a test.  The test declares it wants the
fixture by listing its name as a parameter:

    def test_something(blank_store):   # pytest injects blank_store here
        ...

Fixture scope controls how often the setup runs:
  - "function" (default) — re-runs for every single test.  Changes in one
    test cannot leak into another, which is exactly what we want.
  - "module" / "session" — reused across multiple tests (useful for expensive
    setup like DB connections, but risky if tests mutate shared state).

We use function scope throughout so each test starts in a clean, predictable
state.
"""

import pytest

from inventory_control.store import InventoryStore


# ---------------------------------------------------------------------------
# blank_store
# ---------------------------------------------------------------------------

@pytest.fixture
def blank_store(monkeypatch):
    """
    A fresh InventoryStore with absolutely NO seed data.

    The problem
    -----------
    InventoryStore.__init__ always calls self.seed(), which creates two demo
    parts (ABC-123, XYZ-999) and adds stock.  If every test starts with those
    pre-existing records, it is hard to reason about exact quantities and the
    parts list.

    The solution — monkeypatch
    --------------------------
    pytest's built-in `monkeypatch` fixture temporarily replaces attributes,
    methods, or module-level names for the duration of one test, then
    automatically reverts the change.  Here we replace `seed` with a no-op
    lambda so the store starts completely empty.

    Use blank_store when you want FULL control over initial state — you will
    add exactly the parts and stock you need for your test scenario.
    """
    monkeypatch.setattr(InventoryStore, "seed", lambda self: None)
    return InventoryStore()


# ---------------------------------------------------------------------------
# store  (seeded — normal startup state)
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    """
    A fresh InventoryStore in the standard 'just launched the app' state.

    Seeded contents (defined in InventoryStore.seed):
        ABC-123  Bearing Assembly   min_qty=5   Stock ×12
        XYZ-999  Control Cable      min_qty=2   Stock ×3

    Two RECEIVE transactions are also present from seed.

    Use this fixture when your test represents a realistic operating scenario
    and doesn't need to control the exact starting data from scratch.  It is
    also useful for confirming that behaviour is correct given realistic
    pre-existing data.

    IMPORTANT: every test gets its own independent instance.  Mutations made
    inside one test (receiving, shipping, …) never affect another test.
    """
    return InventoryStore()


# ---------------------------------------------------------------------------
# part_in_store  (blank store + one known part with stock)
# ---------------------------------------------------------------------------

@pytest.fixture
def part_in_store(blank_store):
    """
    A blank store that already has ONE part set up with known stock.

    Part:     TEST-001  "Test Widget"  min_qty=3
    Balance:  Stock ×10

    This fixture demonstrates fixture composition: it builds on top of
    blank_store, which itself builds on top of monkeypatch.  pytest resolves
    the dependency chain automatically — you only need to list part_in_store
    in your test parameter.

    Use this for ship, move, and adjust tests where you need a real part with
    stock but don't want to repeat the setup boilerplate in every test.
    """
    blank_store.add_part("TEST-001", "Test Widget", minimum_quantity=3)
    blank_store.receive("TEST-001", 10, "Stock", "tester", reference="setup")
    return blank_store
