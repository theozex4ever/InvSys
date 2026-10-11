"""Disposable migration inventories; never select an existing database."""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from inventory_control.store import InventoryStore


def create_fixture(directory: Path, *, large: bool = False) -> Path:
    """Create a new directory exclusively, refusing existing paths before any writes.

    All inventory is posted through public store operations so fixtures exercise
    the same ledger and validation as operator work. Failed builds remain for
    diagnosis and have no manifest; callers must use a fresh directory to retry.
    """
    directory.mkdir(parents=True, exist_ok=False)
    database = directory / "inventory.db"
    store = InventoryStore(database, seed=False)
    try:
        for number, minimum, location in (
            ("STANDARD", 5, "Receiving"),
            ("KIT", 0, "Stock"),
            ("SUB", 0, "Stock"),
            ("LEAF", 20, "Stock"),
            ("INACTIVE", 0, "Stock"),
        ):
            store.add_part(number, f"Acceptance {number}", minimum, location)
        for number, lot, quantity in (
            ("STANDARD", "A", 12),
            ("STANDARD", "B", 8),
            ("STANDARD", "ZERO", 1),
            ("KIT", "PARENT", 10),
            ("SUB", "INTERMEDIATE", 10),
            ("LEAF", "A", 5),
            ("LEAF", "B", 30),
            ("INACTIVE", "HELD", 4),
        ):
            store.receive(
                number,
                quantity,
                "Stock",
                lot,
                "Acceptance operator",
                reference="ACCEPT-OPENING",
                notes="Disposable baseline",
            )
        store.adjust("STANDARD", "Stock", "ZERO", 0, "Acceptance operator", "Zero-stock Lot")
        store.move(
            "STANDARD",
            2,
            "Stock",
            "Shipping Bench",
            "B",
            "Acceptance operator",
            reference="ACCEPT-MOVE",
        )
        store.add_bom_component("KIT", "SUB", 2)
        store.add_bom_component("SUB", "LEAF", 3)
        store.add_bom_component("KIT", "LEAF", 1)
        standard = store.ship(
            "STANDARD",
            2,
            "Stock",
            "Standard customer",
            "Acceptance operator",
            lot_number="A",
            carrier="Acceptance carrier",
            tracking="TRACK-STD",
            reference="ACCEPT-STANDARD",
        )
        plan = store.prepare_bom_shipment("KIT", 2, "Stock")
        bom = store.ship(
            "KIT",
            2,
            "Stock",
            "BOM customer",
            "Acceptance operator",
            expected_bom_plan=plan,
            carrier="Acceptance carrier",
            tracking="TRACK-BOM",
            reference="ACCEPT-BOM",
        )
        store.set_part_active("INACTIVE", False)
        store.set_setting("last_operator", "Acceptance operator")
        store.set_setting("desktop_theme", "dark")
        if large:
            _add_large_workload(store)
        manifest = {
            "version": 1,
            "profile": "large" if large else "workflow",
            "database": "inventory.db",
            "parts": len(store.parts),
            "transactions": store.search_history("", "", 1)["total"],
            "expanded_bom_nodes": 1000 if large else 4,
            "bom_root": "PERF-ROOT" if large else "KIT",
            "shipments": [standard, bom],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    finally:
        store.engine.dispose()
    return database


def _add_large_workload(store: InventoryStore) -> None:
    # A bounded-depth tree measures breadth without hitting Python recursion limits.
    numbers = ["PERF-ROOT"] + [f"PERF-{index:05d}" for index in range(1, 9996)]
    store.import_parts(
        [
            dict(
                part_number=number,
                description=f"Performance {number}",
                minimum_quantity=5,
                location="Stock",
                active=index < 1000 or index % 20 != 0,
            )
            for index, number in enumerate(numbers)
        ]
    )
    store.import_bom_components(
        [
            dict(
                parent_part_number=numbers[(index - 1) // 10],
                component_part_number=numbers[index],
                quantity_per=1,
            )
            for index in range(1, 1000)
        ]
    )
    remaining = 100000 - store.search_history("", "", 1)["total"]
    # Distribute records and searchable references across every leaf.
    leaves = numbers[100:1000]
    for start in range(0, remaining, 1000):
        store.import_inventory_receipts(
            [
                dict(
                    part_number=leaves[index % len(leaves)],
                    quantity=1,
                    location="Stock",
                    lot_number=f"PERF-LOT-{(index // len(leaves)) % 3}",
                    reference=f"PERF-RECEIPT-{index:06d}",
                    notes="Large acceptance workload",
                )
                for index in range(start, min(start + 1000, remaining))
            ],
            "Acceptance operator",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--large", action="store_true", help="10k Parts / 100k transactions / 1k BOM nodes"
    )
    args = parser.parse_args()
    # The CLI exposes no operational path argument. A fresh OS temp workspace
    # contains the inventory and any subsequent launcher backups/logs/captures.
    workspace = Path(tempfile.mkdtemp(prefix="invsys-acceptance-"))
    database = create_fixture(workspace / "fixture", large=args.large)
    sys.stdout.write(f"{database}\n")


if __name__ == "__main__":
    main()
