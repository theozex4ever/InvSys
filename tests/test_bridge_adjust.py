"""Adjust Count through the public desktop bridge against real temporary SQLite."""

import pytest

from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore


def _count(counted, expected, **extra):
    return {
        "part_number": "A",
        "location": "Stock",
        "lot_number": "L1",
        "counted": counted,
        "expected": expected,
        "operator": "Pat",
        "reason": "Cycle count",
        **extra,
    }


def _review(counted):
    return {
        "part_number": "A",
        "location": "Stock",
        "lot_number": "L1",
        "counted": counted,
    }


@pytest.fixture
def stocked(tmp_path):
    path = tmp_path / "inventory.db"
    store = InventoryStore(path, seed=False)
    store.add_part("A", "Bearing")
    store.receive("A", 40, "Stock", "L1", "Pat")
    store.receive("A", 6, "Stock", "L2", "Pat")
    store.adjust("A", "Stock", "L2", 0, "Pat", "Emptied")  # zero-stock Lot remains selectable
    return path, store, InventoryBridge(store)


def _balances(bridge):
    context = bridge.stock_context("A")["data"]
    return {(b["location"], b["lot_number"]): b["quantity"] for b in context["part"]["balances"]}


def test_review_reports_authoritative_expected_counted_and_difference(stocked):
    _, _, bridge = stocked
    review = bridge.preview_count(_review(37))
    assert review["ok"]
    data = review["data"]
    assert (data["expected"], data["counted"], data["difference"]) == (40, 37, -3)
    assert data["requires_confirmation"] is False
    assert data["request"] == _review(37)
    assert data["context"]["part"]["quantity"] == 40


def test_found_stock_in_zero_stock_lot_is_recorded_and_survives_restart(stocked):
    path, store, bridge = stocked
    request = _count(5, 0, lot_number=" l2 ", reason=" Found behind shelf ", operator=" Pat ")
    request["part_number"] = " a "
    result = bridge.adjust_count(request)
    assert result["ok"], result
    assert result["data"]["difference"] == 5
    assert result["data"]["context"]["part"]["quantity"] == 45
    store.engine.dispose()
    reopened = InventoryStore(path, seed=False)
    context = InventoryBridge(reopened).stock_context("A")["data"]
    assert {(b["lot_number"]): b["quantity"] for b in context["part"]["balances"]} == {
        "L1": 40,
        "L2": 5,
    }
    tx = context["transactions"][0]
    assert (
        tx["tx_type"],
        tx["quantity_change"],
        tx["lot_number"],
        tx["location_from"],
        tx["location_to"],
        tx["operator"],
        tx["reference"],
    ) == ("COUNT_CORRECTION", 5, "L2", "Stock", "Stock", "Pat", "Found behind shelf")
    reopened.engine.dispose()


def test_matching_count_remains_auditable(stocked):
    _, _, bridge = stocked
    before = len(bridge.stock_context("A")["data"]["transactions"])
    result = bridge.adjust_count(_count(40, 40))
    assert result["ok"]
    assert result["data"]["difference"] == 0
    context = bridge.stock_context("A")["data"]
    assert len(context["transactions"]) == before + 1
    assert context["transactions"][0]["quantity_change"] == 0


@pytest.mark.parametrize(
    "expected, counted, needs",
    [
        (0, 9, False),
        (0, 10, True),
        (21, 30, False),  # +9, half of 21 rounds down to 10
        (21, 31, True),  # +10
        (21, 12, False),  # -9
        (21, 11, True),  # -10
        (40, 59, False),  # +19, threshold 20
        (40, 60, True),
        (40, 21, False),  # -19
        (40, 20, True),  # -20
        (41, 61, True),  # half of 41 rounds down to 20
        (41, 60, False),
        (0, 0, False),
    ],
)
def test_large_correction_threshold_boundaries(tmp_path, expected, counted, needs):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("A", "Bearing")
    store.receive("A", max(expected, 1), "Stock", "L1", "Pat")
    store.adjust("A", "Stock", "L1", expected, "Pat", "Setup")
    bridge = InventoryBridge(store)
    review = bridge.preview_count(_review(counted))["data"]
    assert review["requires_confirmation"] is needs
    before = bridge.stock_context("A")
    unconfirmed = bridge.adjust_count(_count(counted, expected))
    if needs:
        assert unconfirmed["ok"] is False
        assert unconfirmed["error"]["code"] == "CONFIRMATION_REQUIRED"
        assert bridge.stock_context("A") == before
        confirmed = bridge.adjust_count(_count(counted, expected, confirmed=True))
        assert confirmed["ok"], confirmed
    else:
        assert unconfirmed["ok"], unconfirmed
    assert _balances(bridge) == {("Stock", "L1"): counted}
    store.engine.dispose()


def test_changed_stock_since_review_requires_another_review(stocked):
    _, store, bridge = stocked
    store.ship("A", 1, "Stock", "Customer", "Pat", lot_number="L1")
    before = bridge.stock_context("A")
    result = bridge.adjust_count(_count(30, 40, confirmed=True))
    assert result["ok"] is False
    assert result["error"]["code"] == "STALE"
    assert bridge.stock_context("A") == before


@pytest.mark.parametrize(
    "invalid",
    [
        {"counted": -1},
        {"counted": True},
        {"counted": 1.5},
        {"counted": "5"},
        {"counted": None},
        {"counted": 2**31},
        {"expected": -1},
        {"expected": "40"},
        {"expected": True},
        {"reason": " "},
        {"reason": 12},
        {"operator": " "},
        {"operator": None},
        {"location": "missing"},
        {"location": "Receiving"},  # Lot has no balance at this Location
        {"lot_number": "missing"},
        {"lot_number": ""},
        {"part_number": "missing"},
        {"part_number": 12},
        {"confirmed": "yes"},
        {"sql": "DELETE FROM parts"},
    ],
)
def test_invalid_count_requests_have_no_effects(stocked, invalid):
    _, _, bridge = stocked
    before = bridge.stock_context("A")
    result = bridge.adjust_count({**_count(30, 40), **invalid})
    assert result["ok"] is False
    assert result["error"]["code"] in ("VALIDATION", "NOT_FOUND")
    assert bridge.stock_context("A") == before


@pytest.mark.parametrize("invalid", [None, [], {"counted": -1}, {"counted": True}, {"x": 1}])
def test_invalid_review_requests_are_rejected(stocked, invalid):
    _, _, bridge = stocked
    request = {**_review(3), **invalid} if isinstance(invalid, dict) else invalid
    result = bridge.preview_count(request)
    assert result["ok"] is False
    assert result["error"]["code"] in ("VALIDATION", "NOT_FOUND")


def test_review_of_missing_lot_or_location_is_not_found(stocked):
    _, _, bridge = stocked
    assert bridge.preview_count({**_review(3), "lot_number": "NOPE"})["ok"] is False
    assert bridge.preview_count({**_review(3), "location": "Receiving"})["ok"] is False


def test_other_lots_and_locations_are_untouched(stocked):
    _, _, bridge = stocked
    assert bridge.adjust_count(_count(38, 40))["ok"]
    assert _balances(bridge) == {("Stock", "L1"): 38, ("Stock", "L2"): 0}
