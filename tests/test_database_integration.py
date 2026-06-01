import sqlite3

import pytest

from inventory_control.backup import backup_database
from inventory_control.store import InventoryStore


def test_sqlite_store_persists_parts_lots_balances_transactions_and_shipments(tmp_path):
    db_path = tmp_path / "inventory.db"
    store = InventoryStore(db_path=db_path, seed=False)
    store.add_part("ABC-1", "Widget")
    store.receive("ABC-1", 10, "Stock", "LOT-A", "alice", reference="OPENING")
    shipment_number = store.ship("ABC-1", 3, "Stock", "Acme", "bob", "LOT-A")

    reopened = InventoryStore(db_path=db_path, seed=False)

    assert "ABC-1" in reopened.parts
    assert reopened.stock_at("ABC-1", "Stock") == 7
    assert reopened.stock_at("ABC-1", "Stock", "LOT-A") == 7
    assert reopened.lots_for_part("ABC-1")[0].lot_number == "LOT-A"
    assert reopened.shipments[0].shipment_number == shipment_number
    assert [tx.tx_type for tx in reopened.transactions[:2]] == ["SHIP", "RECEIVE"]


def test_receive_requires_real_lot_number(blank_store):
    blank_store.add_part("ABC-1", "Widget")

    with pytest.raises(ValueError, match="Lot required"):
        blank_store.receive("ABC-1", 1, "Stock", "", "alice")


def test_lot_balances_are_isolated_for_shipping(blank_store):
    blank_store.add_part("ABC-1", "Widget")
    blank_store.receive("ABC-1", 5, "Stock", "LOT-A", "alice")
    blank_store.receive("ABC-1", 7, "Stock", "LOT-B", "alice")

    blank_store.ship("ABC-1", 4, "Stock", "Acme", "bob", "LOT-B")

    assert blank_store.stock_at("ABC-1", "Stock") == 8
    assert blank_store.stock_at("ABC-1", "Stock", "LOT-A") == 5
    assert blank_store.stock_at("ABC-1", "Stock", "LOT-B") == 3


def test_selected_lot_must_have_enough_stock_even_when_total_stock_is_enough(blank_store):
    blank_store.add_part("ABC-1", "Widget")
    blank_store.receive("ABC-1", 2, "Stock", "LOT-A", "alice")
    blank_store.receive("ABC-1", 10, "Stock", "LOT-B", "alice")

    with pytest.raises(ValueError, match="Available: 2"):
        blank_store.ship("ABC-1", 5, "Stock", "Acme", "bob", "LOT-A")

    assert blank_store.stock_at("ABC-1", "Stock") == 12


def test_shipment_counter_continues_after_reopen(tmp_path):
    db_path = tmp_path / "inventory.db"
    store = InventoryStore(db_path=db_path, seed=False)
    store.add_part("ABC-1", "Widget")
    store.receive("ABC-1", 5, "Stock", "LOT-A", "alice")
    first = store.ship("ABC-1", 1, "Stock", "First", "bob", "LOT-A")

    reopened = InventoryStore(db_path=db_path, seed=False)
    second = reopened.ship("ABC-1", 1, "Stock", "Second", "bob", "LOT-A")

    assert int(second.split("-")[-1]) == int(first.split("-")[-1]) + 1


def test_backup_database_creates_openable_copy_and_applies_retention(tmp_path):
    db_path = tmp_path / "inventory.db"
    backup_dir = tmp_path / "backups"
    store = InventoryStore(db_path=db_path, seed=False)
    store.add_part("ABC-1", "Widget")

    backup = backup_database(db_path=db_path, backup_dir=backup_dir, keep=1)
    backup_database(db_path=db_path, backup_dir=backup_dir, keep=1)

    assert backup is not None
    assert len(list(backup_dir.glob("inventory-*.db"))) == 1
    with sqlite3.connect(backup) as connection:
        part_count = connection.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    assert part_count == 1
