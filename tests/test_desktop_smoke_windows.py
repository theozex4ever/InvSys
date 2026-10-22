"""A successful shell call alone must not establish native folder acceptance."""

import json
import sys

import pytest

from inventory_control import desktop_smoke_windows, utilities


@pytest.mark.skipif(sys.platform != "win32", reason="requires the real Windows Explorer observer")
def test_a_noop_system_opener_cannot_report_successful_folder_navigation(tmp_path, monkeypatch):
    evidence = tmp_path / "observations.json"
    probe = desktop_smoke_windows.FolderProbe(evidence)
    # Mock only the OS boundary: still inspect the actual Explorer windows. This
    # catches the original gap where merely recording a request established success.
    monkeypatch.setattr(utilities.os, "startfile", lambda _path: None)
    monkeypatch.setattr(desktop_smoke_windows, "EXPLORER_TIMEOUT_SECONDS", 1)
    with pytest.raises(OSError, match="No new visible Explorer window navigated"):
        utilities.NativeHost(opener=probe.open_folder).open_folder(tmp_path)
    assert probe.opened_folders == []
    assert json.loads(evidence.read_text()) == []
