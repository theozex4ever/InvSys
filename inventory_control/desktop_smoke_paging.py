"""Native smoke: real keys page through a catalog larger than one page and keep focus.

The Parts table shows 100 rows a page. Activating Previous/Next rebuilds the pager; focus
must stay on the equivalent enabled control (not fall to the page) and the new page must be
announced, or a keyboard user has to walk 100 rows to find the pager again.
"""

import json
import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from inventory_control.desktop_smoke_ui import _GuiActions

EXTRA_PARTS = 105  # one full page of 100 and a second page of 5


def check_catalog_paging(window: Any, wait: Any) -> None:
    run = window.evaluate_js
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Native paging smoke requires the Qt application.")
    actions = _GuiActions()
    actions.moveToThread(app.thread())

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop paging smoke failed: {label}")

    def activate() -> None:
        window.native.raise_()
        window.native.activateWindow()
        QApplication.setActiveWindow(window.native)
        window.native.webview.setFocus(Qt.FocusReason.OtherFocusReason)

    def key(code: Any) -> None:
        actions.run(lambda: QTest.keyClick(window.native.webview.focusProxy(), code))

    prefix = f"PAGING-{time.time_ns()}"
    # Real Parts through the bridge, so the catalog needs a second page.
    run(f"""
        window.smokePaged = null;
        (async () => {{
            for (let index = 0; index < {EXTRA_PARTS}; index++) {{
                const created = await window.pywebview.api.create_part({{
                    part_number: {json.dumps(prefix)} + '-' + String(index).padStart(3, '0'),
                    description: 'Paging smoke', minimum_quantity: 0, location: 'Stock'}});
                if (!created.ok) {{ window.smokePaged = created; return; }}
            }}
            window.smokePaged = {{ok: true}};
        }})();
    """)
    wait("window.smokePaged", 180)
    require("window.smokePaged.ok", "creating the Parts for a second page")

    window.resize(1366, 768)
    actions.run(activate)
    wait("document.hasFocus()")
    run("document.querySelector('[data-page=parts]').click()")
    wait("document.querySelector('#query').getClientRects().length")
    run(
        f"document.querySelector('#query').value = {json.dumps(prefix)}; "
        "document.querySelector('#query').dispatchEvent(new Event('input', {bubbles: true}))"
    )
    page = "document.querySelectorAll('#parts-data tbody tr').length === {rows} && document.querySelector('#parts-data .table-footer').textContent.includes('{total} parts · Page {number} of 2')"
    wait(page.format(rows=100, total=EXTRA_PARTS, number=1))

    focused = "document.activeElement.dataset.pg === '{target}' && !document.activeElement.disabled"
    visible = "getComputedStyle(document.activeElement).outlineStyle !== 'none'"
    # Forward with Enter: Next becomes disabled on the last page, so focus moves to Previous.
    run("document.querySelector('[data-pg=\"1\"]').focus()")
    require(focused.format(target=1), "Next takes keyboard focus")
    key(Qt.Key.Key_Return)
    wait(page.format(rows=EXTRA_PARTS - 100, total=EXTRA_PARTS, number=2))
    require(focused.format(target=0), "focus stays on the pager (Previous) after the last page")
    require(visible, "pager focus is visible after paging forward")
    require(
        "document.querySelector('#notice').textContent === 'Page 2 of 2'",
        "the new page is announced",
    )
    # Back with Enter: Previous becomes disabled on the first page, so focus moves to Next.
    key(Qt.Key.Key_Return)
    wait(page.format(rows=100, total=EXTRA_PARTS, number=1))
    require(focused.format(target=1), "focus stays on the pager (Next) after the first page")
    require(visible, "pager focus is visible after paging back")
    require(
        "document.querySelector('#notice').textContent === 'Page 1 of 2'",
        "the first page is announced again",
    )
    # Leave the catalog as the other checks expect it.
    run("document.querySelector('#clear').click()")
    wait("document.querySelector('#query').value === ''")
    print(
        "Desktop smoke: catalog paging with real keys keeps pager focus and announces each page.",
        flush=True,
    )
