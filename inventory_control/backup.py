import errno
import os
import shutil
import sqlite3
from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
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
    except OSError:
        # A partial file must never be listed as the latest backup.
        target.unlink(missing_ok=True)
        raise

    for old in _backup_files(backup_dir)[keep:]:
        # Retention is housekeeping: a file that cannot be pruned must not fail a good backup.
        with suppress(OSError):
            old.unlink(missing_ok=True)
    return target


def _backup_files(backup_dir: Path) -> list[Path]:
    # iterdir (unlike glob) raises on an unreadable folder instead of returning nothing.
    found = [path for path in backup_dir.iterdir() if fnmatch(path.name, "inventory-*.db")]
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def describe_backup(path: Path) -> BackupInfo:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return BackupInfo(path.name, path, stat.st_size, modified)


def list_backups(backup_dir: Path) -> list[BackupInfo]:
    """Backups in ``backup_dir``, newest first. Raises OSError if they cannot be read."""
    if not backup_dir.exists():
        return []
    if not backup_dir.is_dir():
        raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(backup_dir))
    return [describe_backup(path) for path in _backup_files(backup_dir)]


def verify_backup(path: Path) -> None:
    """Reopen a backup read-only and check its integrity; raise sqlite3.Error if unusable."""
    # immutable=1 keeps the check from creating WAL sidecars beside the backup.
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)) as copy:
        result = copy.execute("PRAGMA quick_check").fetchall()
    if result != [("ok",)]:
        raise sqlite3.DatabaseError("integrity check failed")


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
