import errno
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from inventory_control.config import BACKUP_DIR, DB_PATH

DEFAULT_RETENTION = 20


@dataclass(frozen=True)
class BackupInfo:
    name: str
    path: Path
    size_bytes: int
    modified: str


def backup_database(
    db_path: Path = DB_PATH,
    backup_dir: Path = BACKUP_DIR,
    keep: int = DEFAULT_RETENTION,
    reason: str = "",
) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = _backup_target(backup_dir, reason)
    try:
        # sqlite3's own context manager only commits; closing() releases the file
        # handles so retention can delete old backups (Windows locks open files).
        with (
            closing(sqlite3.connect(db_path)) as source,
            closing(sqlite3.connect(target)) as destination,
        ):
            source.backup(destination)
    except sqlite3.Error:
        shutil.copy2(db_path, target)

    for old in _backup_files(backup_dir)[keep:]:
        old.unlink(missing_ok=True)
    return target


def _backup_files(backup_dir: Path) -> list[Path]:
    return sorted(
        backup_dir.glob("inventory-*.db"), key=lambda path: path.stat().st_mtime, reverse=True
    )


def list_backups(backup_dir: Path) -> list[BackupInfo]:
    """Backups in ``backup_dir``, newest first. Raises OSError if they cannot be read."""
    if backup_dir.exists() and not backup_dir.is_dir():
        raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(backup_dir))
    infos = []
    for path in _backup_files(backup_dir):
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        infos.append(BackupInfo(path.name, path, stat.st_size, modified))
    return infos


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
