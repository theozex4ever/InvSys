#!/usr/bin/env python3
"""The last known-good release for the upgrade and rollback rehearsal.

No packaged release of InvSys exists before the desktop packages, so the last known-good
artifact is the original PySide6 application as the repository recorded it just before
the pywebview frontend was added: commit ``COMMIT`` (merge of PR #5). It is a source
tree, run the way that release ran (``python inventory_visualizer.py``), and it keeps its
inventory at ``data/inventory.db`` beside its code: it has no database option.

This module is used in two ways. ``upgrade_rehearsal.py`` imports it to extract that tree
from git history. The tree's own code runs only in a child interpreter started as

    python -I scripts/last_known_good.py build-fixture --tree T --database D
    python -I scripts/last_known_good.py rollback-probe --tree T

so that the historical ``inventory_control`` package never mixes with the checkout's.
``build-fixture`` writes the committed pre-migration inventory with the old store;
``rollback-probe`` opens the original application's real startup and main window on an
upgraded inventory and then works with that release's own store.
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime, tzinfo
from pathlib import Path, PurePosixPath
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
# Merge of PR #5 (2026-09-28): the last commit before the desktop frontend.
COMMIT = "a03c887dd76056695f81e55d0ff1cac4315ee444"
# Operator named on every record the rollback probe writes.
PROBE_OPERATOR = "Last known-good"


class ReleaseUnavailable(Exception):
    """The pinned release cannot be extracted; the message says how to fix that."""


def _git(*arguments: str) -> bytes:
    # Fixed git subcommands on a pinned commit; no operator input reaches the command.
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(ROOT), *arguments],  # noqa: S607
            capture_output=True,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ReleaseUnavailable(
            f"The last known-good release {COMMIT[:7]} could not be read from git history "
            f"({exc.__class__.__name__}). The rehearsal needs the repository's full history: "
            f"run `git fetch --unshallow` (or `git fetch origin {COMMIT}`) and retry."
        ) from exc
    return result.stdout


def tree_hash() -> str:
    """The content hash of the pinned tree (what makes the pin tamper-evident)."""
    return _git("rev-parse", f"{COMMIT}^{{tree}}").decode().strip()


def extract(destination: Path) -> dict[str, Any]:
    """Unpack the pinned release into the new directory ``destination``."""
    destination.mkdir(parents=True)
    archive = _git("archive", "--format=tar", COMMIT)
    files = 0
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        # Byte-code that happened to be committed is for another interpreter; skip it.
        members = [
            member
            for member in bundle.getmembers()
            if "__pycache__" not in PurePosixPath(member.name).parts
        ]
        bundle.extractall(
            destination, members=members, filter="data"
        )  # the repository's own history, vetted by the data filter
        files = sum(1 for member in members if member.isfile())
    return {
        "kind": "source-tree",
        "commit": COMMIT,
        "tree": tree_hash(),
        "files": files,
        "inventory": "data/inventory.db",
        "launch": "python inventory_visualizer.py",
    }


def run_release(command: str, tree: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run ``command`` of this module with the extracted release's code, in its folder."""
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    # The interpreter running the rehearsal and this module; -I keeps the checkout and any
    # PYTHON* variables out of the historical release's import path.
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            command,
            "--tree",
            str(tree),
            *arguments,
        ],
        cwd=tree,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )


def release_database(tree: Path) -> Path:
    return tree / "data" / "inventory.db"


def release_backups(tree: Path) -> Path:
    return tree / "backups"


# ------------------------------------------------------- code run with the old release


def _use_release(tree: Path) -> None:
    sys.path.insert(0, str(tree))
    import inventory_control

    if not Path(inventory_control.__file__).resolve().is_relative_to(tree.resolve()):
        raise SystemExit(f"{inventory_control.__file__} is not the release under {tree}.")


class _Clock:
    """Deterministic wall clock for the fixture generator."""

    def __init__(self) -> None:
        self.current = datetime(2026, 9, 1, 9, 0)

    def at(self, day: int, hour: int = 9, minute: int = 0) -> None:
        self.current = datetime(2026, 9, day, hour, minute)


def build_fixture(tree: Path, database: Path) -> None:
    """Write the pre-migration scenario with the release's own store and a fixed clock."""
    _use_release(tree)
    from inventory_control.store import InventoryStore

    clock = _Clock()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FrozenDateTime":  # noqa: ARG003  # mirrors datetime.now
            moment = clock.current
            return cls(moment.year, moment.month, moment.day, moment.hour, moment.minute)

    # Both modules stamp rows (and the shipment number) with datetime.now().
    with (
        mock.patch("inventory_control.store.datetime", FrozenDateTime),
        mock.patch("inventory_control.migrations.datetime", FrozenDateTime),
    ):
        store = InventoryStore(database, seed=False)
        try:
            _scenario(store, clock)
        finally:
            store.engine.dispose()


def _scenario(store: Any, clock: _Clock) -> None:
    clock.at(1)
    catalog = (
        ("UPG-FRAME", "Frame assembly (phantom, nested)", 2, "Stock"),
        ("UPG-SUB", "Sub-assembly (phantom, intermediate)", 0, "Stock"),
        ("UPG-BOLT", "Bolt M6 (leaf)", 40, "Stock"),
        ("UPG-PLATE", "Mounting plate (leaf)", 5, "Stock"),
        ("UPG-GASKET", "Gasket (leaf)", 10, "Receiving"),
        ("UPG-WIDGET", "Widget (standard Part)", 20, "Stock"),
        ("UPG-LOW", "Low stock sensor", 10, "Stock"),
        ("UPG-RETIRED", "Retired fitting", 0, "Receiving"),
    )
    for number, description, minimum, location in catalog:
        store.add_part(number, description, minimum, location, notify=False)
    store.add_bom_component("UPG-FRAME", "UPG-SUB", 2, notify=False)
    store.add_bom_component("UPG-FRAME", "UPG-BOLT", 4, notify=False)
    store.add_bom_component("UPG-FRAME", "UPG-PLATE", 1, notify=False)
    store.add_bom_component("UPG-SUB", "UPG-BOLT", 2, notify=False)
    store.add_bom_component("UPG-SUB", "UPG-GASKET", 1, notify=False)

    clock.at(2)
    for number, quantity, location, lot in (
        ("UPG-BOLT", 60, "Stock", "B-100"),
        ("UPG-BOLT", 40, "Stock", "B-200"),
        ("UPG-PLATE", 10, "Stock", "P-1"),
        ("UPG-GASKET", 25, "Receiving", "G-1"),
        ("UPG-WIDGET", 80, "Stock", "W-1"),
        ("UPG-WIDGET", 40, "Receiving", "W-2"),
        ("UPG-LOW", 15, "Stock", "L-1"),
        ("UPG-RETIRED", 5, "Receiving", "R-1"),
    ):
        store.receive(number, quantity, location, lot, "A. Rivera", "PO-2026-0901", notify=False)

    clock.at(3)
    store.move("UPG-GASKET", 25, "Receiving", "Stock", "G-1", "A. Rivera", "Putaway")
    store.move("UPG-WIDGET", 20, "Receiving", "Stock", "W-2", "A. Rivera", "Putaway")

    clock.at(4)
    store.ship(
        "UPG-WIDGET",
        30,
        "Stock",
        "Acme Co",
        "J. Okafor",
        lot_number="W-1",
        carrier="Parcel Express",
        tracking="PX-100200300",
        reference="SO-5001",
    )
    store.ship("UPG-LOW", 12, "Stock", "Beta GmbH", "J. Okafor", lot_number="L-1")

    clock.at(5)
    plan = store.prepare_bom_shipment("UPG-FRAME", 3, "Stock")
    store.ship("UPG-FRAME", 3, "Stock", "Gamma Ltd", "J. Okafor", expected_bom_plan=plan)
    clock.at(6)
    store.adjust("UPG-WIDGET", "Stock", "W-2", 18, "A. Rivera", "Cycle count: two damaged")
    store.adjust("UPG-RETIRED", "Receiving", "R-1", 0, "A. Rivera", "Written off")
    store.adjust("UPG-RETIRED", "Receiving", "R-1", 2, "A. Rivera", "Found two on the shelf")
    store.set_part_active("UPG-RETIRED", False, notify=False)

    clock.at(8)
    plan = store.prepare_bom_shipment("UPG-FRAME", 5, "Stock")
    store.ship(
        "UPG-FRAME",
        5,
        "Stock",
        "Delta SA",
        "J. Okafor",
        expected_bom_plan=plan,
        reference="SO-5002",
    )

    clock.at(9)
    store.move("UPG-BOLT", 2, "Stock", "Scrap", "B-200", "A. Rivera", "Damaged")
    # The BOM changes after the shipments above; their component snapshots must not.
    store.add_bom_component("UPG-FRAME", "UPG-BOLT", 5, notify=False)
    store.add_bom_component("UPG-FRAME", "UPG-GASKET", 1, notify=False)
    store.set_setting("last_operator", "J. Okafor")
    store.set_setting("desktop_theme", "dark")


def rollback_probe(tree: Path) -> dict[str, Any]:
    """Start the original application on the inventory in its folder, then work as it does.

    ``inventory_control.app.main`` is the release's real entry point: it takes the startup
    backup, builds the main window (every view reads the inventory) and enters the Qt event
    loop, which is told to quit once the window is shown. The release's own store then reads
    and writes the inventory as its views would.
    """
    _use_release(tree)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from inventory_control import app as original_app
    from inventory_control.ui import main_window

    shown: list[Any] = []
    real_show = main_window.MainWindow.show

    def show_then_quit(window: Any) -> None:
        real_show(window)
        shown.append(window)
        QTimer.singleShot(300, QApplication.instance().quit)

    main_window.MainWindow.show = show_then_quit  # type: ignore[method-assign]  # one-shot child process
    exit_code = original_app.main()

    from inventory_control.backup import backup_database
    from inventory_control.config import BACKUP_DIR, DB_PATH
    from inventory_control.store import STORE

    read = _read_inventory(STORE)
    operator = PROBE_OPERATOR
    STORE.receive("UPG-WIDGET", 3, "Stock", "LKG-1", operator, "rollback rehearsal")
    STORE.move("UPG-WIDGET", 1, "Stock", "Shipping Bench", "LKG-1", operator, "rollback rehearsal")
    STORE.ship("UPG-WIDGET", 2, "Stock", "Rollback Co", operator, lot_number="W-1")
    plan = STORE.prepare_bom_shipment("UPG-FRAME", 1, "Stock")
    if not plan.ready:
        raise SystemExit("The release could not plan a frame shipment from the upgraded stock.")
    bom_shipment = STORE.ship(
        "UPG-FRAME", 1, "Stock", "Rollback BOM Co", operator, expected_bom_plan=plan
    )
    STORE.adjust("UPG-LOW", "Stock", "L-1", 5, operator, "rollback rehearsal count")
    STORE.set_setting("last_operator", operator)
    manual = backup_database(DB_PATH, BACKUP_DIR, reason="manual")
    return {
        "exit_code": exit_code,
        "windows_shown": len(shown),
        "release": str(Path(original_app.__file__).resolve().parent.parent),
        "read_before_work": read,
        "bom_shipment": bom_shipment,
        "manual_backup": manual.name if manual else None,
    }


def _read_inventory(store: Any) -> dict[str, Any]:
    """What the release itself sees: its counts and every BOM shipment's component trace."""
    shipments = store.shipments
    return {
        "parts": len(store.parts),
        "transactions": len(store.transactions),
        "shipments": len(shipments),
        "component_snapshots": {
            shipment.shipment_number: sorted(
                [item.part_number, item.lot_number, item.location, item.quantity]
                for item in shipment.consumed_components
            )
            for shipment in shipments
            if shipment.consumed_components
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("build-fixture")
    fixture.add_argument("--tree", type=Path, required=True)
    fixture.add_argument("--database", type=Path, required=True)
    probe = commands.add_parser("rollback-probe")
    probe.add_argument("--tree", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build-fixture":
        build_fixture(args.tree.resolve(), args.database.resolve())
        return 0
    print(json.dumps(rollback_probe(args.tree.resolve())))  # the runner reads this line
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
