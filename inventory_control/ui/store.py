"""The original Qt application's shared store, initialized only when its UI loads."""

from inventory_control.store import InventoryStore

STORE = InventoryStore(db_path=None, seed=False)
