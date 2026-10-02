"""Optional serverless desktop launcher; the original Qt launcher stays available."""

import argparse
import logging
import sys
from pathlib import Path

from inventory_control.backup import backup_database
from inventory_control.bridge import InventoryBridge
from inventory_control.config import BACKUP_DIR, DB_PATH, LOG_DIR, PROJECT_ROOT
from inventory_control.store import InventoryStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="InvSys desktop (built assets, no HTTP server)"
    )
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
    if not all(
        (assets / name).is_file() for name in ("index.html", "app.js", "style.css")
    ):
        parser.error(
            "Built frontend assets are missing. Run npm ci and npm run build in frontend/."
        )
    try:
        import webview
    except ImportError:
        parser.error(
            "Install requirements-desktop.txt before launching the desktop application."
        )

    database = args.database.resolve() if args.database else DB_PATH
    backups = database.parent / "backups" if args.database else BACKUP_DIR
    logs = database.parent / "logs" if args.database else LOG_DIR
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=logs / "desktop.log", level=logging.INFO)
    backup_database(db_path=database, backup_dir=backups, reason="startup")
    store = InventoryStore(database, seed=False)
    try:
        window = webview.create_window(
            "InvSys",
            url=(assets / "index.html").as_uri(),
            js_api=InventoryBridge(store),
            width=1366,
            height=768,
            min_size=(640, 480),
        )
        # file:// avoids pywebview's automatic server for bare filesystem paths.
        if args.smoke_check:
            from inventory_control.desktop_smoke import DesktopSmoke

            smoke = DesktopSmoke()
            smoke.prepare_bom(store)
            webview.start(smoke.run, window, gui="qt", http_server=False)
            if smoke.error:
                logging.getLogger(__name__).error(
                    "Desktop smoke failed: %s", smoke.error
                )
                print(f"Desktop smoke failed: {smoke.error}", file=sys.stderr)
                return 1
            if webview.http.global_server is not None:
                print(
                    "Desktop smoke failed: an HTTP server was started.", file=sys.stderr
                )
                return 1
        else:
            webview.start(gui="qt", http_server=False)
    finally:
        store.engine.dispose()
    if args.smoke_check:
        reopened = InventoryStore(database, seed=False)
        try:
            bridge = InventoryBridge(reopened)
            if (
                bridge.preferences()["data"]["operator"] != "Desktop smoke"
                or not bridge.part_detail("DESKTOP-SMOKE")["ok"]
                or bridge.stock_context("DESKTOP-SMOKE")["data"] != smoke.stock_result
                or bridge.shipment_detail(smoke.bom_result["shipment_number"])["data"]
                != smoke.bom_result
                or bridge.part_detail(smoke.bom_part)["data"]["quantity"] != 10
                or bridge.part_detail(smoke.bom_sub)["data"]["quantity"] != 10
                or bridge.part_detail(smoke.bom_leaf)["data"]["quantity"] != 8
            ):
                print("Desktop smoke failed: restart persistence.", file=sys.stderr)
                return 1
            print("Desktop smoke: restart persistence passed; no HTTP server.")
        finally:
            reopened.engine.dispose()
    return 0
