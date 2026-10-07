import os
from pathlib import Path

APP_NAME = "Inventory Control MVP"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# INVSYS_HOME relocates the operational data, backups, exports and logs as a unit.
# The test suite points it at a throwaway directory so no test can open the real
# operational database; operators can use it to keep data outside the checkout.
APP_HOME = Path(os.environ.get("INVSYS_HOME") or PROJECT_ROOT).resolve()
DATA_DIR = APP_HOME / "data"
BACKUP_DIR = APP_HOME / "backups"
EXPORT_DIR = APP_HOME / "exports"
LOG_DIR = APP_HOME / "logs"
DB_PATH = DATA_DIR / "inventory.db"
