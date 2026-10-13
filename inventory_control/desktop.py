"""Optional serverless desktop launcher; the original Qt launcher stays available."""

import argparse
import importlib.util
import logging
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from inventory_control.backup import backup_database
from inventory_control.bridge import InventoryBridge
from inventory_control.config import PROJECT_ROOT
from inventory_control.store import InventoryStore
from inventory_control.utilities import NativeHost, UtilityContext

if TYPE_CHECKING:
    from inventory_control.desktop_smoke import DesktopSmoke


def main() -> int:
    parser = argparse.ArgumentParser(description="InvSys desktop (built assets, no HTTP server)")
    parser.add_argument(
        "--database",
        type=Path,
        help="Explicit review database; backups/logs stay beside it",
    )
    parser.add_argument(
        "--assets",
        type=Path,
        help="Built frontend directory (default: bundled frontend/dist)",
    )
    parser.add_argument(
        "--smoke-check",
        action="store_true",
        help="Exercise real desktop reads/writes and exit; requires a disposable --database",
    )
    args = parser.parse_args()
    if args.smoke_check and args.database is None:
        parser.error("--smoke-check requires an explicit disposable --database.")
    if getattr(sys, "frozen", False) and args.database is None:
        parser.error(
            "Packaged launch requires --database to choose the intended inventory file explicitly."
        )
    asset_root = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    assets = (args.assets or asset_root / "frontend" / "dist").resolve()
    if not all((assets / name).is_file() for name in ("index.html", "app.js", "style.css")):
        parser.error(
            "Built frontend assets are missing. Run npm ci and npm run build in frontend/."
        )
    if importlib.util.find_spec("webview") is None:
        parser.error("Install requirements-desktop.txt before launching the desktop application.")
    import webview
    import webview.http as webview_http

    context = UtilityContext.for_launch(args.database)
    database = context.database
    context.logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=context.logs / "desktop.log", level=logging.INFO)
    backup_database(db_path=database, backup_dir=context.backups, reason="startup")
    store = InventoryStore(database, seed=False)
    smoke: DesktopSmoke | None = None
    # The smoke records folder requests instead of opening a file manager window.
    opened_folders: list[Path] = []
    host = NativeHost(opener=opened_folders.append) if args.smoke_check else NativeHost()
    try:
        window = webview.create_window(
            "InvSys",
            url=(assets / "index.html").as_uri(),
            js_api=InventoryBridge(store, context, host),
            width=1366,
            height=768,
            min_size=(640, 480),
        )
        host.attach(window)
        # file:// avoids pywebview's automatic server for bare filesystem paths.
        if args.smoke_check:
            from inventory_control import desktop_smoke

            smoke = desktop_smoke.DesktopSmoke(database.parent / "smoke-captures")
            smoke.opened_folders = opened_folders
            smoke.prepare_bom(store)
            webview.start(smoke.run, (window,), gui="qt", http_server=False)
            if smoke.error:
                logging.getLogger(__name__).error("Desktop smoke failed: %s", smoke.error)
                print(f"Desktop smoke failed: {smoke.error}", file=sys.stderr)
                return 1
            # The stubs type global_server as always None; widen to check at runtime.
            server: object = webview_http.global_server
            if server is not None:
                print("Desktop smoke failed: an HTTP server was started.", file=sys.stderr)
                return 1
        else:
            webview.start(gui="qt", http_server=False)
    finally:
        store.engine.dispose()
    if smoke is not None:
        if (
            smoke.bom_result is None
            or smoke.recovered_bom_result is None
            or smoke.adjust_result is None
        ):
            print("Desktop smoke failed: BOM or adjust results were not captured.", file=sys.stderr)
            return 1
        if smoke.backup_path is None or not smoke.backup_path.is_file():
            print("Desktop smoke failed: manual backup file is missing.", file=sys.stderr)
            return 1
        if smoke.backup_path.parent != context.backups:
            print(
                "Desktop smoke failed: backup left the selected database folder.", file=sys.stderr
            )
            return 1
        reopened = InventoryStore(database, seed=False)
        try:
            bridge = InventoryBridge(reopened)
            if (
                bridge.preferences()["data"] != {"operator": "Desktop smoke", "theme": "dark"}
                or not bridge.part_detail("DESKTOP-SMOKE")["ok"]
                or bridge.part_detail(smoke.imported_part)["data"]["description"]
                != "Reviewed bearing"
                or bridge.stock_context("DESKTOP-SMOKE")["data"] != smoke.stock_result
                or bridge.stock_context(smoke.adjust_part)["data"] != smoke.adjust_result
                or bridge.shipment_detail(smoke.bom_result["shipment_number"])["data"]
                != smoke.bom_result
                or bridge.shipment_detail(smoke.recovered_bom_result["shipment_number"])["data"]
                != smoke.recovered_bom_result
                or bridge.part_detail(smoke.bom_part)["data"]["quantity"] != 10
                or bridge.part_detail(smoke.bom_sub)["data"]["quantity"] != 10
                or bridge.part_detail(smoke.bom_leaf)["data"]["quantity"]
                != 8 + smoke.explore_receipt
            ):
                print("Desktop smoke failed: restart persistence.", file=sys.stderr)
                return 1
            authored = smoke.bom_authoring
            if (
                authored is None
                or bridge.bom_definition(authored["parent"])["data"] != authored["definition"]
                or bridge.shipment_detail(authored["shipment"]["shipment_number"])["data"]
                != authored["shipment"]
            ):
                print("Desktop smoke failed: BOM authoring restart persistence.", file=sys.stderr)
                return 1
            # Immutable read-only: inspecting a backup must not change it or leave WAL sidecars.
            with closing(
                sqlite3.connect(f"{smoke.backup_path.as_uri()}?mode=ro&immutable=1", uri=True)
            ) as copy:
                row = copy.execute("SELECT 1 FROM parts WHERE part_number = 'DESKTOP-SMOKE'")
                if row.fetchone() is None:
                    print("Desktop smoke failed: backup content.", file=sys.stderr)
                    return 1
            print("Desktop smoke: restart persistence and backup content passed; no HTTP server.")
        finally:
            reopened.engine.dispose()
        # Qt WebEngine can hang during interpreter teardown on the headless CI runner after
        # every check has passed; the verdict is already printed, so skip finalization.
        sys.stdout.flush()  # pragma: no cover - only reachable in the native smoke
        sys.stderr.flush()  # pragma: no cover
        os._exit(0)  # pragma: no cover
    return 0
