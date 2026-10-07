"""
test_stock_ledger.py — Tests for the Stock ledger invariants.

Covers:
  - Every Stock balance equals the sum of its non-phantom transaction rows
  - Shortage messages from ship and move report actual quantities
  - Observers are notified once after a committed mutation and never after a
    rejected one
  - Every row written by one mutation shares one timestamp

All checks go through the public InventoryStore API against a real temporary
SQLite database.
"""

from collections import Counter
from itertools import count

import pytest

from inventory_control.store import InventoryStore


@pytest.fixture
def db_store(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    yield store
    store.engine.dispose()


def ledger_totals(store):
    """Sum non-phantom transaction rows per (part, lot, location)."""
    totals = Counter()
    for tx in store.transactions:
        if tx.tx_type == "SHIP_BOM":
            continue
        location = tx.location_to if tx.quantity_change > 0 else tx.location_from
        totals[(tx.part_number, tx.lot_number, location)] += tx.quantity_change
    return totals


def balance_totals(store):
    return {
        (balance.part_number, balance.lot_number, balance.location): balance.quantity
        for part_number in store.parts
        for balance in store.lot_balances(part_number)
    }


def snapshot(store):
    return balance_totals(store), store.transactions, store.shipments


class TestLedgerInvariant:
    def test_balances_equal_sum_of_transactions_after_mixed_activity(self, db_store):
        db_store.add_part("KIT", "Kit")
        db_store.add_part("SUB", "Subassembly")
        db_store.add_part("MAT-1", "Material 1")
        db_store.add_part("MAT-2", "Material 2")
        db_store.add_part("PART", "Standard part")
        db_store.add_bom_component("KIT", "SUB", 2)
        db_store.add_bom_component("KIT", "MAT-1", 1)
        db_store.add_bom_component("SUB", "MAT-2", 3)

        db_store.receive("MAT-1", 3, "Stock", "L1", "alice")
        db_store.receive("MAT-1", 3, "Stock", "L2", "alice")
        db_store.receive("MAT-2", 20, "Stock", "A", "alice")
        db_store.receive("PART", 10, "Stock", "LOT-1", "alice")
        db_store.import_inventory_receipts(
            [
                {
                    "part_number": "PART",
                    "lot_number": "LOT-2",
                    "quantity": 4,
                    "location": "Receiving",
                },
                {
                    "part_number": "MAT-1",
                    "lot_number": "L1",
                    "quantity": 2,
                    "location": "Stock",
                },
            ],
            "importer",
        )
        db_store.ship("PART", 3, "Stock", "Acme", "bob", "LOT-1")
        plan = db_store.prepare_bom_shipment("KIT", 3, "Stock")
        db_store.ship("KIT", 3, "Stock", "Acme", "bob", expected_bom_plan=plan)
        db_store.move("PART", 2, "Stock", "Shipping Bench", "LOT-1", "carol")
        db_store.adjust("PART", "Receiving", "LOT-2", 9, "dave", "Recount up")
        db_store.adjust("PART", "Stock", "LOT-1", 1, "dave", "Recount down")

        balances = balance_totals(db_store)
        assert balances == dict(ledger_totals(db_store))
        assert balances[("MAT-1", "L1", "Stock")] == 2
        assert balances[("MAT-2", "A", "Stock")] == 2
        assert balances[("PART", "LOT-1", "Shipping Bench")] == 2
        assert balances[("PART", "LOT-2", "Receiving")] == 9
        assert balances[("PART", "LOT-1", "Stock")] == 1


class TestShortageMessages:
    def test_ship_beyond_available_reports_quantities_and_changes_nothing(self, db_store):
        db_store.add_part("PART", "Standard part")
        db_store.receive("PART", 10, "Stock", "LOT-1", "alice")
        before = snapshot(db_store)

        with pytest.raises(
            ValueError, match=r"^Not enough stock\. Available: 10, requested: 11\.$"
        ):
            db_store.ship("PART", 11, "Stock", "Acme", "bob", "LOT-1")

        assert snapshot(db_store) == before

    def test_ship_from_location_without_balance_reports_zero_available(self, db_store):
        db_store.add_part("PART", "Standard part")
        db_store.receive("PART", 10, "Stock", "LOT-1", "alice")
        before = snapshot(db_store)

        with pytest.raises(ValueError, match=r"^Not enough stock\. Available: 0, requested: 3\.$"):
            db_store.ship("PART", 3, "Receiving", "Acme", "bob", "LOT-1")

        assert snapshot(db_store) == before

    def test_move_beyond_available_reports_quantities_and_changes_nothing(self, db_store):
        db_store.add_part("PART", "Standard part")
        db_store.receive("PART", 10, "Stock", "LOT-1", "alice")
        before = snapshot(db_store)

        with pytest.raises(
            ValueError, match=r"^Not enough stock\. Available: 10, requested: 12\.$"
        ):
            db_store.move("PART", 12, "Stock", "Shipping Bench", "LOT-1", "carol")

        assert snapshot(db_store) == before

    def test_move_from_location_without_balance_reports_zero_available(self, db_store):
        db_store.add_part("PART", "Standard part")
        db_store.receive("PART", 10, "Stock", "LOT-1", "alice")
        before = snapshot(db_store)

        with pytest.raises(ValueError, match=r"^Not enough stock\. Available: 0, requested: 5\.$"):
            db_store.move("PART", 5, "Receiving", "Stock", "LOT-1", "carol")

        assert snapshot(db_store) == before


class TestMutationNotifications:
    @pytest.fixture
    def stocked(self, db_store):
        db_store.add_part("PART", "Standard part")
        db_store.receive("PART", 10, "Stock", "LOT-1", "alice")
        calls = []
        db_store.subscribe(lambda: calls.append(db_store.stock_at("PART", "Stock", "LOT-1")))
        return db_store, calls

    @pytest.mark.parametrize(
        "mutation, expected_stock",
        [
            (lambda store: store.ship("PART", 4, "Stock", "Acme", "bob", "LOT-1"), 6),
            (
                lambda store: store.move("PART", 4, "Stock", "Shipping Bench", "LOT-1", "carol"),
                6,
            ),
            (
                lambda store: store.adjust("PART", "Stock", "LOT-1", 7, "dave", "Recount"),
                7,
            ),
        ],
        ids=["ship", "move", "adjust"],
    )
    def test_subscriber_is_called_once_after_commit(self, stocked, mutation, expected_stock):
        store, calls = stocked

        mutation(store)

        # The observer reads committed stock, so it ran after the commit.
        assert calls == [expected_stock]

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda store: store.ship("PART", 11, "Stock", "Acme", "bob", "LOT-1"),
            lambda store: store.move("PART", 11, "Stock", "Shipping Bench", "LOT-1", "carol"),
            lambda store: store.adjust("PART", "Stock", "NO-LOT", 7, "dave", "Recount"),
        ],
        ids=["ship", "move", "adjust"],
    )
    def test_subscriber_is_not_called_after_rejection(self, stocked, mutation):
        store, calls = stocked

        with pytest.raises(ValueError):
            mutation(store)

        assert calls == []

    def test_receipt_import_notifies_once(self, stocked):
        store, calls = stocked

        store.import_inventory_receipts(
            [
                {
                    "part_number": "PART",
                    "lot_number": "LOT-1",
                    "quantity": 1,
                    "location": "Stock",
                },
                {
                    "part_number": "PART",
                    "lot_number": "LOT-1",
                    "quantity": 2,
                    "location": "Stock",
                },
            ],
            "importer",
        )

        assert calls == [13]

    def test_receive_with_notify_false_does_not_notify(self, stocked):
        store, calls = stocked

        store.receive("PART", 1, "Stock", "LOT-1", "alice", notify=False)

        assert calls == []


class TestSharedTimestamp:
    @pytest.fixture
    def ticking_store(self, db_store, monkeypatch):
        ticks = count()
        monkeypatch.setattr(db_store, "now", lambda: f"2026-10-06 {next(ticks):05d}")
        return db_store

    def test_move_rows_share_one_timestamp(self, ticking_store):
        ticking_store.add_part("PART", "Standard part")
        ticking_store.receive("PART", 10, "Stock", "LOT-1", "alice")

        ticking_store.move("PART", 4, "Stock", "Shipping Bench", "LOT-1", "carol")

        move_in, move_out = ticking_store.transactions[:2]
        assert (move_in.tx_type, move_out.tx_type) == ("MOVE_IN", "MOVE_OUT")
        assert move_in.timestamp == move_out.timestamp

    def test_bom_shipment_rows_share_the_shipment_timestamp(self, ticking_store):
        ticking_store.add_part("KIT", "Kit")
        ticking_store.add_part("MAT-1", "Material 1")
        ticking_store.add_bom_component("KIT", "MAT-1", 2)
        ticking_store.receive("MAT-1", 2, "Stock", "L1", "alice")
        ticking_store.receive("MAT-1", 2, "Stock", "L2", "alice")
        plan = ticking_store.prepare_bom_shipment("KIT", 2, "Stock")

        ticking_store.ship("KIT", 2, "Stock", "Acme", "bob", expected_bom_plan=plan)

        shipment = ticking_store.shipments[0]
        rows = ticking_store.transactions[:3]
        assert [row.tx_type for row in rows] == [
            "SHIP_BOM",
            "BOM_CONSUME",
            "BOM_CONSUME",
        ]
        assert {row.timestamp for row in rows} == {shipment.timestamp}

    def test_standard_shipment_row_shares_the_shipment_timestamp(self, ticking_store):
        ticking_store.add_part("PART", "Standard part")
        ticking_store.receive("PART", 10, "Stock", "LOT-1", "alice")

        ticking_store.ship("PART", 4, "Stock", "Acme", "bob", "LOT-1")

        assert ticking_store.transactions[0].timestamp == ticking_store.shipments[0].timestamp
