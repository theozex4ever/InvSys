"""The export keyboard check sends one Shift+Tab and still fails when it has no effect."""

import pytest

from inventory_control.desktop_smoke_ui import shift_tab_to_previous_export


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
