"""Drive the Windows common file dialog that Qt shows for native dialogs.

On Windows ``QFileDialog.getOpenFileName`` opens the system's own dialog; the
``QFileDialog`` widget Qt keeps is only a shell, so selecting a file in the widget
never reaches the dialog the operator sees. This types a path into the real dialog's
filename field and presses its Open or Cancel button, in the process that owns it.
"""

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

DIALOG_CLASS = "#32770"
FILENAME_COMBO_ID = 0x47C
IDOK = 1
IDCANCEL = 2
WM_SETTEXT = 0x000C
BM_CLICK = 0x00F5


def _user32() -> Any:
    if sys.platform == "win32":
        user32 = ctypes.WinDLL("user32")
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
        user32.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetDlgItem.restype = wintypes.HWND
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
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
        pid = wintypes.DWORD()
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
