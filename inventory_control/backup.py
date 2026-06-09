from datetime import datetime
from pathlib import Path
import shutil
import sqlite3

from inventory_control.config import BACKUP_DIR, DB_PATH


def backup_database(
    db_path: Path = DB_PATH,
    backup_dir: Path = BACKUP_DIR,
    keep: int = 20,
    reason: str = "",
) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = _backup_target(backup_dir, reason)
    try:
        with sqlite3.connect(db_path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    except sqlite3.Error:
        shutil.copy2(db_path, target)

    backups = sorted(backup_dir.glob("inventory-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)
    return target


def _backup_target(backup_dir: Path, reason: str = "") -> Path:
    suffix = _normalize_reason(reason)
    stem = f"inventory-{datetime.now().strftime('%Y%m%d-%H%M%S')}{suffix}"
    target = backup_dir / f"{stem}.db"
    counter = 1
    while target.exists():
        target = backup_dir / f"{stem}-{counter:02d}.db"
        counter += 1
    return target


def _normalize_reason(reason: str) -> str:
    cleaned = reason.strip().lower().replace("_", "-").replace(" ", "-")
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "-")
    return f"-{cleaned}" if cleaned else ""
