"""Native keyboard probes use current layout and reject ineffective keys without retries."""

import pytest
from PySide6.QtCore import Qt

from inventory_control.desktop_smoke_ui import (
    check_graph_keyboard_view,
    shift_tab_to_previous_export,
)


class Page:
    """A fake page whose focus moves only when a key is effective."""

    def __init__(self, effective: bool, settled_after: int = 0):
        self.focus = "inventory"
        self.effective = effective
        self.keys = 0
        self.settled_after = settled_after
        self.waits: list[str] = []

    def key(self):
        self.keys += 1
        if self.effective:
            self.focus = "parts"

    def wait(self, condition: str):
        self.waits.append(condition)
        if "exportKind === 'parts'" in condition and self.focus != "parts":
            raise RuntimeError(f"Desktop smoke timed out: {condition}")

    def run(self, script: str):
        return True


def test_an_effective_key_moves_focus_after_the_page_settles():
    page = Page(effective=True)
    shift_tab_to_previous_export(page.key, page.wait, page.run)
    assert page.keys == 1
    assert page.focus == "parts"
    assert page.waits[0].startswith("document.hasFocus()")


def test_a_delivered_but_ineffective_key_is_not_retried_and_fails():
    page = Page(effective=False)
    with pytest.raises(RuntimeError, match="timed out"):
        shift_tab_to_previous_export(page.key, page.wait, page.run)
    assert page.keys == 1


class GraphPage:
    """A graph with an initial transform left over from a previous viewport size."""

    def __init__(self, ineffective=None):
        self.transform = "old fit"
        self.baseline = None
        self.ineffective = ineffective
        self.keys = []

    def run(self, script):
        if "[data-bomx=fit]" in script:
            self.transform = "current fit"
        if "window.smokeGraphFit=" in script:
            self.baseline = self.transform

    def wait(self, condition):
        if "getAttribute('transform') === smokeGraphFit" in condition:
            assert self.transform == self.baseline
        elif "getAttribute('transform') !== smokeGraphFit" in condition:
            assert self.transform != self.baseline

    def key(self, code):
        self.keys.append(code)
        if code == self.ineffective:
            return
        self.transform = "current fit" if code == Qt.Key.Key_0 else "changed"


def test_graph_keyboard_fit_uses_the_current_viewport_not_the_initial_transform():
    page = GraphPage()
    check_graph_keyboard_view(page.key, page.wait, page.run)
    assert page.keys == [Qt.Key.Key_Right, Qt.Key.Key_0, Qt.Key.Key_Plus, Qt.Key.Key_0]


@pytest.mark.parametrize("ineffective", [Qt.Key.Key_Right, Qt.Key.Key_Plus, Qt.Key.Key_0])
def test_graph_keyboard_probe_rejects_an_ineffective_key(ineffective):
    page = GraphPage(ineffective)
    with pytest.raises(AssertionError):
        check_graph_keyboard_view(page.key, page.wait, page.run)
    assert page.keys.count(ineffective) == 1
