from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

from inventory_control.config import BACKUP_DIR, DB_PATH


def backup_database(db_path: Path = DB_PATH, backup_dir: Path = BACKUP_DIR, keep: int = 20) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"inventory-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    try:
        with sqlite3.connect(db_path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    except sqlite3.Error:
        shutil.copy2(db_path, target)

    backups = sorted(backup_dir.glob("inventory-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)
    return target
