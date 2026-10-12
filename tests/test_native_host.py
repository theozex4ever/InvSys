"""Native desktop operations behind the bridge, with the platform calls replaced.

The real file manager and file dialog are exercised by the native smoke; these
cases pin the command selection, failure reporting and cancellation semantics.
"""

import subprocess
from pathlib import Path

import pytest

from inventory_control import utilities
from inventory_control.utilities import NativeHost, open_with_system


class FakeProcess:
    def __init__(self, returncode: int | None = 0) -> None:
        self.returncode = returncode
        self.waited = False

    def wait(self, timeout: float | None = None) -> int:
        self.waited = True
        if self.returncode is None:
            if timeout is not None:
                raise subprocess.TimeoutExpired("opener", timeout)
            return 0
        return self.returncode


def patch_popen(monkeypatch, process: FakeProcess | None = None, error: OSError | None = None):
    commands: list[list[str]] = []

    def popen(command, **_options):
        commands.append(command)
        if error is not None:
            raise error
        assert process is not None
        return process

    monkeypatch.setattr(utilities.subprocess, "Popen", popen)
    return commands


def test_linux_and_macos_open_the_folder_with_the_platform_opener(monkeypatch, tmp_path):
    commands = patch_popen(monkeypatch, FakeProcess(0))
    open_with_system(tmp_path, platform="linux")
    open_with_system(tmp_path, platform="darwin")
    assert commands == [["xdg-open", str(tmp_path)], ["open", str(tmp_path)]]


def test_opener_failure_is_reported_instead_of_ignored(monkeypatch, tmp_path):
    patch_popen(monkeypatch, FakeProcess(3))
    with pytest.raises(OSError, match="exit"):
        open_with_system(tmp_path, platform="linux")


def test_missing_opener_is_reported(monkeypatch, tmp_path):
    patch_popen(monkeypatch, error=FileNotFoundError("xdg-open"))
    with pytest.raises(OSError, match="xdg-open"):
        open_with_system(tmp_path, platform="linux")


def test_opener_that_keeps_running_is_a_launched_file_manager(monkeypatch, tmp_path):
    process = FakeProcess(None)
    patch_popen(monkeypatch, process)
    open_with_system(tmp_path, platform="linux")
    assert process.waited


def test_native_host_opens_folders_through_its_opener(tmp_path):
    opened: list[Path] = []
    NativeHost(opener=opened.append).open_folder(tmp_path)
    assert opened == [tmp_path]


class FakeWindow:
    def __init__(self, selection) -> None:
        self.selection = selection
        self.calls: list[dict] = []

    def create_file_dialog(self, dialog_type, directory="", allow_multiple=False, file_types=()):
        self.calls.append(
            {
                "dialog_type": dialog_type,
                "directory": directory,
                "allow_multiple": allow_multiple,
                "file_types": file_types,
            }
        )
        return self.selection


def test_file_selection_starts_in_the_given_folder_and_returns_one_path(tmp_path):
    chosen = tmp_path / "parts.csv"
    window = FakeWindow((str(chosen),))
    host = NativeHost()
    host.attach(window)
    assert host.choose_file(tmp_path, ("CSV files (*.csv)",)) == chosen
    call = window.calls[0]
    assert call["directory"] == str(tmp_path)
    assert call["allow_multiple"] is False
    assert call["file_types"] == ("CSV files (*.csv)",)


@pytest.mark.parametrize("selection", [None, (), []])
def test_cancelling_file_selection_is_an_ordinary_result(tmp_path, selection):
    host = NativeHost()
    host.attach(FakeWindow(selection))
    assert host.choose_file(tmp_path) is None


def test_file_selection_requires_the_desktop_window(tmp_path):
    with pytest.raises(RuntimeError, match="window"):
        NativeHost().choose_file(tmp_path)
