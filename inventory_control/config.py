from pathlib import Path


APP_NAME = "Inventory Control MVP"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = PROJECT_ROOT / "backups"
LOG_DIR = PROJECT_ROOT / "logs"
DB_PATH = DATA_DIR / "inventory.db"
