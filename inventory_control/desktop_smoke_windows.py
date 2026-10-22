"""Drive native Windows CSV dialogs and verify actual Explorer folder navigation.

On Windows ``QFileDialog.getOpenFileName`` opens the system's own dialog; the
``QFileDialog`` widget Qt keeps is only a shell, so selecting a file in the widget
never reaches the dialog the operator sees. This types a path into the real dialog's
filename field and presses its Open or Cancel button, in the process that owns it.
"""

import ctypes
import ctypes.wintypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from inventory_control.utilities import open_with_system

DIALOG_CLASS = "#32770"
FILENAME_COMBO_ID = 0x47C
IDOK = 1
IDCANCEL = 2
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5
WM_CLOSE = 0x0010
EXPLORER_TIMEOUT_SECONDS = 20

# Shell.Windows exposes the displayed FolderItem's filesystem path and HWND.
# Only read Explorer windows; no path or other input is interpolated into this script.
EXPLORER_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$shell = New-Object -ComObject Shell.Application
$windows = @($shell.Windows() | ForEach-Object {
    if ([System.IO.Path]::GetFileName($_.FullName) -ieq 'explorer.exe') {
        [PSCustomObject]@{
            hwnd = [long]$_.HWND
            path = [string]$_.Document.Folder.Self.Path
            location_url = [string]$_.LocationURL
        }
    }
})
ConvertTo-Json -Compress -InputObject $windows
"""


def _user32() -> Any:
    if sys.platform == "win32":
        user32 = ctypes.WinDLL("user32")
        callback = ctypes.WINFUNCTYPE(
            ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )
        user32.EnumWindows.argtypes = [callback, ctypes.wintypes.LPARAM]
        user32.EnumChildWindows.argtypes = [ctypes.wintypes.HWND, callback, ctypes.wintypes.LPARAM]
        user32.GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ]
        user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
        user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
        user32.PostMessageW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        ]
        user32.GetDlgItem.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
        user32.GetDlgItem.restype = ctypes.wintypes.HWND
        user32.SendMessageW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.c_void_p,
        ]
        user32.callback_type = callback
        return user32
    raise RuntimeError("The Windows file dialog driver only runs on Windows.")


def _class_name(user32: Any, hwnd: int) -> str:
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, 64)
    return str(name.value)


def find_file_dialog() -> int | None:
    """Handle of this process's visible common file dialog, if one is open."""
    user32 = _user32()
    found: list[int] = []

    def visit(hwnd: int, _: int) -> bool:
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if (
            pid.value == os.getpid()
            and user32.IsWindowVisible(hwnd)
            and _class_name(user32, hwnd) == DIALOG_CLASS
        ):
            found.append(hwnd)
        return True

    user32.EnumWindows(user32.callback_type(visit), 0)
    return found[0] if found else None


def _filename_edit(user32: Any, dialog: int) -> int | None:
    edits: list[int] = []

    def visit(hwnd: int, _: int) -> bool:
        if _class_name(user32, hwnd) == "Edit":
            edits.append(hwnd)
        return True

    # The filename combo box wraps the field; fall back to the dialog's first edit control.
    user32.EnumChildWindows(
        user32.GetDlgItem(dialog, FILENAME_COMBO_ID) or dialog, user32.callback_type(visit), 0
    )
    return edits[0] if edits else None


def press(path: Path | None) -> bool:
    """Type ``path`` and press Open, or press Cancel for None; False if the dialog is not ready."""
    user32 = _user32()
    dialog = find_file_dialog()
    if dialog is None:
        return False
    if path is not None:
        edit = _filename_edit(user32, dialog)
        if edit is None:
            return False
        text = ctypes.create_unicode_buffer(str(path))
        user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.addressof(text))
    button = user32.GetDlgItem(dialog, IDCANCEL if path is None else IDOK)
    if not button:
        return False
    user32.SendMessageW(button, BM_CLICK, 0, None)
    return True


def explorer_windows() -> list[dict[str, Any]]:
    """Read actual Explorer navigation through Windows' built-in COM automation."""
    powershell = (
        Path(os.environ["SYSTEMROOT"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    # A fixed Windows tool and read-only script, without shell interpolation.
    result = subprocess.run(  # noqa: S603
        [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", EXPLORER_SCRIPT],
        capture_output=True,
        encoding="utf-8-sig",
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(f"Cannot inspect Explorer navigation: {result.stderr.strip()}")
    windows: list[dict[str, Any]] = json.loads(result.stdout)
    return windows


class FolderProbe:
    """Open real folders, require visible Explorer navigation, and retain observations.

    Each requested path belongs to the disposable launch-selected inventory. A new
    window is required so an old window cannot hide a broken/no-op system opener.
    Only that newly observed Explorer window is closed, never unrelated windows.
    """

    def __init__(self, evidence: Path) -> None:
        self.evidence = evidence
        self.opened_folders: list[Path] = []
        self.observations: list[dict[str, Any]] = []
        self._save()

    def _save(self) -> None:
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        self.evidence.write_text(json.dumps(self.observations, indent=2) + "\n", encoding="utf-8")

    def open_folder(self, path: Path) -> None:
        before = {item["hwnd"] for item in explorer_windows()}
        open_with_system(path)
        user32 = _user32()
        deadline = time.monotonic() + EXPLORER_TIMEOUT_SECONDS
        windows: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            windows = explorer_windows()
            for item in windows:
                if (
                    item["hwnd"] not in before
                    and Path(item["path"]) == path
                    and user32.IsWindowVisible(item["hwnd"])
                ):
                    observation = {**item, "requested": str(path), "visible": True}
                    self.observations.append(observation)
                    self._save()
                    user32.PostMessageW(item["hwnd"], WM_CLOSE, 0, 0)
                    closed_by = time.monotonic() + 5
                    while user32.IsWindow(item["hwnd"]) and time.monotonic() < closed_by:
                        time.sleep(0.1)
                    observation["closed_after_probe"] = not user32.IsWindow(item["hwnd"])
                    self._save()
                    if not observation["closed_after_probe"]:
                        raise OSError(f"Explorer did not close the smoke window for {path}.")
                    self.opened_folders.append(Path(item["path"]))
                    print(
                        f"Desktop smoke: visible Explorer navigation verified: {path}", flush=True
                    )
                    return
            time.sleep(0.2)
        raise OSError(f"No new visible Explorer window navigated to {path}. Observed: {windows}")
