"""Launch-aware desktop utility context and native operations.

``UtilityContext`` names the database and the backup, export and log folders of the
inventory chosen at launch. ``DesktopHost`` is the narrow set of native operations
(open a folder, choose a file) the bridge may request; it never exposes paths the
bridge did not derive from the context.
"""

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from inventory_control.config import BACKUP_DIR, DB_PATH, EXPORT_DIR, LOG_DIR

# How long to wait for an opener to fail before treating it as a launched file manager.
_OPENER_GRACE_SECONDS = 3.0


@dataclass(frozen=True)
class UtilityContext:
    database: Path
    backups: Path
    exports: Path
    logs: Path

    @classmethod
    def for_launch(cls, database: Path | None = None) -> "UtilityContext":
        """Source default (honouring INVSYS_HOME) or the folders beside an explicit database."""
        if database is None:
            return cls(DB_PATH, BACKUP_DIR, EXPORT_DIR, LOG_DIR)
        database = database.resolve()
        base = database.parent
        return cls(database, base / "backups", base / "exports", base / "logs")


class DesktopHost(Protocol):
    def open_folder(self, path: Path) -> None:
        """Show ``path`` in the platform file manager; raise OSError if that fails."""

    def choose_file(self, directory: Path, file_types: Sequence[str] = ()) -> Path | None:
        """Ask the operator for one existing file; None means the dialog was cancelled."""


def _open_command(path: Path, platform: str) -> list[str]:
    return ["open" if platform == "darwin" else "xdg-open", str(path)]


def open_with_system(path: Path, platform: str = sys.platform) -> None:
    if platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined,unused-ignore]  # noqa: S606  # Windows-only API; path comes from the launch context, never operator input
        return
    # Fixed opener binary plus a path derived from the launch context, no shell.
    process = subprocess.Popen(  # noqa: S603
        _open_command(path, platform),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        code = process.wait(timeout=_OPENER_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        # Some openers stay alive for as long as the file manager does; reap it later.
        threading.Thread(target=process.wait, daemon=True).start()
        return
    if code != 0:
        raise OSError(f"The system file manager could not open the folder (exit status {code}).")


class NativeHost:
    """Platform file manager and pywebview file dialog."""

    def __init__(self, opener: Callable[[Path], None] = open_with_system) -> None:
        self._opener = opener
        self._window: Any = None

    def attach(self, window: Any) -> None:
        self._window = window

    def open_folder(self, path: Path) -> None:
        self._opener(path)

    def choose_file(self, directory: Path, file_types: Sequence[str] = ()) -> Path | None:
        if self._window is None:
            raise RuntimeError("The desktop window is not ready for file selection.")
        import webview

        selection = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            directory=str(directory),
            allow_multiple=False,
            file_types=tuple(file_types),
        )
        return Path(selection[0]) if selection else None
