"""A successful shell call alone must not establish native folder acceptance."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from inventory_control import desktop_smoke_windows, utilities


@pytest.mark.skipif(sys.platform != "win32", reason="requires the real Windows Explorer observer")
def test_a_noop_system_opener_cannot_report_successful_folder_navigation(tmp_path, monkeypatch):
    evidence = tmp_path / "observations.json"
    probe = desktop_smoke_windows.FolderProbe(evidence)
    # Mock only the OS boundary: still inspect the actual Explorer windows. This
    # catches the original gap where merely recording a request established success.
    monkeypatch.setattr(utilities.os, "startfile", lambda _path: None)
    monkeypatch.setattr(desktop_smoke_windows, "EXPLORER_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(desktop_smoke_windows, "EXPLORER_CLEANUP_SECONDS", 0.5)
    with pytest.raises(OSError, match=r"No new visible Explorer|Explorer snapshot exceeded"):
        utilities.NativeHost(opener=probe.open_folder).open_folder(tmp_path)
    assert probe.opened_folders == []
    assert json.loads(evidence.read_text()) == []


def test_slow_folder_navigation_finishes_inside_the_folder_ui_wait(tmp_path, monkeypatch):
    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(desktop_smoke_windows, "time", clock)
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path))
    # A slow initial snapshot (14s), system opener (6s), and first navigation
    # snapshot (14s) consume 34s. The final snapshot must use only the remaining
    # observation time, with cleanup still inside the end-to-end probe budget.
    delays = iter((14, 14, 0.5))
    timeouts = []
    observed = {"hwnd": 123, "path": str(tmp_path), "location_url": tmp_path.as_uri()}

    def snapshot(command, *, timeout, **_kwargs):
        timeouts.append(timeout)
        delay = next(delays)
        assert delay < timeout
        clock.sleep(delay)
        windows = [observed] if len(timeouts) == 3 else []
        return subprocess.CompletedProcess(command, 0, json.dumps(windows), "")

    monkeypatch.setattr(desktop_smoke_windows.subprocess, "run", snapshot)
    monkeypatch.setattr(desktop_smoke_windows, "open_with_system", lambda _path: clock.sleep(6))
    user32 = SimpleNamespace(
        IsWindowVisible=lambda _hwnd: True,
        PostMessageW=lambda *_args: clock.sleep(3),
        IsWindow=lambda _hwnd: False,
    )
    monkeypatch.setattr(desktop_smoke_windows, "_user32", lambda: user32)
    evidence = tmp_path / "observations.json"
    probe = desktop_smoke_windows.FolderProbe(evidence)
    utilities.NativeHost(opener=probe.open_folder).open_folder(tmp_path)
    assert clock.now == pytest.approx(37.7)
    assert clock.now < desktop_smoke_windows.folder_wait_seconds("win32")
    assert timeouts[:2] == [15, 15]
    assert timeouts[2] == pytest.approx(0.8)
    assert probe.opened_folders == [tmp_path]
    assert json.loads(evidence.read_text())[0]["closed_after_probe"] is True
    for platform in ("linux", "darwin"):
        assert desktop_smoke_windows.folder_wait_seconds(platform) == 20
