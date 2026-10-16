"""Native smoke for numbered destinations, contextual state, History sorting and accessibility."""

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from inventory_control.desktop_smoke_ui import PAGES, _GuiActions

# The original application's Ctrl+1–9 destinations and each page's primary input.
DESTINATIONS = (
    ("dashboard", "#dashboard-data .attention-row [data-part]"),
    ("parts", "#query"),
    ("bom", "#bom-parent"),
    ("receive", "#receive-part_number"),
    ("ship", "#ship-part_number"),
    ("move", "#move-part_number"),
    ("history", "#history-query"),
    ("settings", "#settings h1"),
    ("adjust", "#adjust-part_number"),
)

# Rendered WCAG 2.2 contrast (1.4.3) and accessible-name checks for visible content.
# Disabled controls are exempt; gradient/image backgrounds are reported as skipped.
_AUDIT = """
window.smokeAudit = root => {
  const parse = value => { const m = /rgba?\\(([^)]+)\\)/.exec(value); if (!m) return null; const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const blend = (top, bottom) => [0, 1, 2].map(i => top[i] * top[3] + bottom[i] * (1 - top[3])).concat(1);
  const channel = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const luminance = c => 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2]);
  const ratio = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const background = element => {
    const layers = [];
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage !== 'none') return null;
      const color = parse(style.backgroundColor);
      if (color && color[3] > 0) { layers.push(color); if (color[3] >= 1) break; }
    }
    return layers.reverse().reduce((base, layer) => blend(layer, base), [255, 255, 255, 1]);
  };
  // SVG text paints with fill over its node card, not CSS color over a background.
  const paint = e => { const s = getComputedStyle(e), c = parse(s.fill); if (c) c[3] *= Number(s.fillOpacity); return c; };
  const svgBackground = e => {
    const base = background(e.ownerSVGElement), card = e.parentElement?.querySelector(':scope > rect'), fill = card && paint(card);
    return base && fill ? blend(fill, base) : base;
  };
  const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const text = e => Array.from(e.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
  const failures = [], skipped = [];
  let checked = 0;
  for (const e of root.querySelectorAll('*')) {
    if (!visible(e) || e.closest(':disabled, [aria-disabled=true]')) continue;
    if (!text(e) && !e.matches('input:not([type=checkbox]):not([type=radio]), select, textarea')) continue;
    const style = getComputedStyle(e);
    const svg = e instanceof SVGElement;
    const fg = svg ? paint(e) : parse(style.color), bg = svg ? svgBackground(e) : background(e);
    if (!fg || !bg) { skipped.push(e.tagName + '.' + e.getAttribute('class')); continue; }
    const size = parseFloat(style.fontSize), bold = Number(style.fontWeight) >= 700;
    const required = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const value = ratio(blend(fg, bg), bg);
    checked++;
    if (value < required) failures.push(`${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}.${e.getAttribute('class')} "${e.textContent.trim().slice(0, 40)}" ${value.toFixed(2)} < ${required}`);
  }
  const name = e => (e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') || '').split(/\\s+/).map(id => document.getElementById(id)?.textContent || '').join('') || e.textContent || e.title || '').trim();
  for (const e of root.querySelectorAll('button, a[href], [role=button], [tabindex="0"]')) if (visible(e) && !name(e)) failures.push(`unnamed ${e.outerHTML.slice(0, 80)}`);
  for (const e of root.querySelectorAll('input, select, textarea')) if (visible(e) && !e.labels?.length && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby')) failures.push(`unlabelled #${e.id}`);
  for (const e of document.querySelectorAll('dialog')) if (!name(e) || !e.getAttribute('aria-labelledby')) failures.push(`unlabelled dialog #${e.id}`);
  return {failures, skipped: Array.from(new Set(skipped)), checked};
};
"""


def check_navigation(window: Any, wait: Any) -> dict[str, Any]:
    """Run after every workflow smoke so all pages hold real data."""
    run = window.evaluate_js

    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Native navigation smoke requires the Qt application.")
    actions = _GuiActions()
    actions.moveToThread(app.thread())

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop navigation smoke failed: {label}")

    def activate() -> None:
        window.native.raise_()
        window.native.activateWindow()
        QApplication.setActiveWindow(window.native)
        window.native.webview.setFocus(Qt.FocusReason.OtherFocusReason)

    def key(code: Any, modifiers: Any = Qt.KeyboardModifier.NoModifier) -> None:
        actions.run(lambda: QTest.keyClick(window.native.webview.focusProxy(), code, modifiers))

    control = Qt.KeyboardModifier.ControlModifier
    digits = [getattr(Qt.Key, f"Key_{index}") for index in range(1, 10)]
    window.resize(1366, 768)
    actions.run(activate)
    wait("document.hasFocus()")

    # Each real Ctrl+digit opens its destination and focuses the primary input,
    # even when pressed from inside another page's text field.
    run("document.querySelector('[data-page=parts]').click()")
    wait("document.querySelector('#query').getClientRects().length")
    run("document.querySelector('#query').focus()")
    for index, ((page, primary), digit) in enumerate(zip(DESTINATIONS, digits, strict=True)):
        key(digit, control)
        wait(
            f"!document.querySelector('#{page}').hidden && document.querySelector('[data-page={page}].nav-button').getAttribute('aria-current') === 'page'"
        )
        fallback = f"#{page} h1"
        wait(
            f"document.activeElement === document.querySelector({json.dumps(primary)}) || document.activeElement === document.querySelector({json.dumps(fallback)})"
        )
        require(
            "getComputedStyle(document.activeElement).outlineStyle !== 'none'",
            f"Ctrl+{index + 1} focus is visible on {page}",
        )
        require(
            f"document.querySelector('[data-page={page}].nav-button').getAttribute('aria-keyshortcuts').startsWith('Control+')",
            f"{page} announces its shortcut",
        )
    # Ctrl+K selects the kept query, so typing replaces it as in the original.
    run(
        "const q = document.querySelector('#query'); q.value = 'KEEP'; q.dispatchEvent(new Event('input')); document.querySelector('[data-page=dashboard]').click();"
    )
    key(Qt.Key.Key_K, control)
    wait("!document.querySelector('#parts').hidden && document.activeElement.id === 'query'")
    actions.run(lambda: QTest.keyClicks(window.native.webview.focusProxy(), "ZX"))
    wait("document.querySelector('#query').value === 'ZX'")
    run("document.querySelector('#clear').click()")

    # Shortcuts never navigate behind an open dialog.
    run("document.querySelector('#add-part').click()")
    wait("document.querySelector('#create-dialog').open")
    key(Qt.Key.Key_1, control)
    key(Qt.Key.Key_K, control)
    require(
        "document.querySelector('#create-dialog').open && !document.querySelector('#parts').hidden",
        "shortcuts are ignored while a dialog is open",
    )
    run("document.querySelector('#close-create').click()")
    wait("!document.querySelector('#create-dialog').open")

    # Contextual Move keeps the catalog filters, sort and selection for the return trip.
    run("""
        const set = (id, value) => { const e = document.querySelector(id); if (e.type === 'checkbox') e.checked = value; else e.value = value; e.dispatchEvent(new Event(e.tagName === 'INPUT' && e.type !== 'checkbox' ? 'input' : 'change')); };
        set('#query', 'DESKTOP-SMOKE'); set('#filter-status', 'active'); set('#sort', 'quantity'); set('#descending', true);
    """)
    wait("document.querySelector('#parts-data [data-part=DESKTOP-SMOKE]')")
    run("document.querySelector('#parts-data [data-part=DESKTOP-SMOKE]').click()")
    wait("document.querySelector('#drawer-data [data-stock=move]')")
    run("document.querySelector('#drawer-data [data-stock=move]').click()")
    wait(
        "!document.querySelector('#move').hidden && document.querySelector('#move-part_number').value === 'DESKTOP-SMOKE' && !document.querySelector('#drawer').open"
    )
    run("document.querySelector('#move-quantity').value = '1'")
    actions.run(activate)
    wait("document.hasFocus()")
    key(Qt.Key.Key_2, control)
    wait("!document.querySelector('#parts').hidden && document.activeElement.id === 'query'")
    require(
        "document.querySelector('#query').value === 'DESKTOP-SMOKE' && document.querySelector('#filter-status').value === 'active' && document.querySelector('#sort').value === 'quantity' && document.querySelector('#descending').checked && document.querySelector('#parts-data tr.selected [data-part=DESKTOP-SMOKE]')",
        "catalog filters, sort and selected Part survive contextual navigation",
    )
    key(Qt.Key.Key_6, control)
    wait(
        "!document.querySelector('#move').hidden && document.activeElement.id === 'move-part_number'"
    )
    require(
        "document.querySelector('#move-part_number').value === 'DESKTOP-SMOKE' && document.querySelector('#move-quantity').value === '1'",
        "Move draft survives shortcut navigation",
    )
    run(
        "document.querySelector('#move-quantity').value = ''; document.querySelector('#clear').click()"
    )

    # History: Python search over Notes/Locations/type text and server-side column sort.
    key(Qt.Key.Key_7, control)
    wait("document.activeElement.id === 'history-query'")
    for query, sort, descending in (
        ("Inspected", "timestamp", True),
        ("shipping bench", "location_to", False),
        ("move_", "quantity_change", False),
        ("DESKTOP-SMOKE", "quantity_change", True),
        ("DESKTOP-SMOKE", "lot_number", False),
    ):
        request = json.dumps(dict(query=query, sort=sort, descending=descending))
        run(f"""
            window.smokeHistoryTruth = null;
            window.smokeAPI.history({request}).then(r => {{ window.smokeHistoryTruth = r.data; }});
            const q = document.querySelector('#history-query'); q.value = {json.dumps(query)}; q.dispatchEvent(new Event('input'));
            const s = document.querySelector('#history-sort'); s.value = {json.dumps(sort)}; s.dispatchEvent(new Event('change'));
            const d = document.querySelector('#history-descending'); d.checked = {json.dumps(descending)}; d.dispatchEvent(new Event('change'));
        """)
        wait(
            "window.smokeHistoryTruth && !document.querySelector('#history-data').textContent.includes('Loading')"
        )
        require(
            "window.smokeHistoryTruth.records.length > 0 && JSON.stringify(Array.from(document.querySelectorAll('#history-data [data-history-id]')).map(b => Number(b.dataset.historyId))) === JSON.stringify(window.smokeHistoryTruth.records.map(r => r.transaction_id))",
            f"History renders Python's {sort} order for {query!r}",
        )
    run("document.querySelector('[data-page=dashboard]').click()")
    key(Qt.Key.Key_7, control)
    wait("document.activeElement.id === 'history-query'")
    require(
        "document.querySelector('#history-query').value === 'DESKTOP-SMOKE' && document.querySelector('#history-sort').value === 'lot_number' && !document.querySelector('#history-descending').checked",
        "History search and sort survive navigation",
    )
    run("document.querySelector('#history-clear').click()")
    wait("!document.querySelector('#history-data').textContent.includes('Loading')")
    require(
        "document.querySelector('#history-sort').value === 'timestamp' && document.querySelector('#history-descending').checked && document.querySelector('#history-query').value === ''",
        "Clear filters restores newest-first History",
    )

    # Rendered contrast and accessible names on every page in both themes.
    run(_AUDIT)
    # The audit must catch planted failures before a clean result means anything.
    run("""
        (() => {
            const probe = document.createElement('div');
            probe.innerHTML = '<p style="color:#b0b0b0;background:#fff">Low contrast probe</p><button></button><svg width="200" height="40" style="color:#111"><g><rect width="200" height="40" fill="#fff"/><text x="5" y="25" fill="#f4f4f4">SVG probe</text></g></svg>';
            document.querySelector('main').append(probe);
            window.smokeProbe = window.smokeAudit(probe).failures; probe.remove();
        })();
    """)
    probe = run("window.smokeProbe")
    if not (
        any("Low contrast probe" in item for item in probe)
        and any("SVG probe" in item for item in probe)
        and any(item.startswith("unnamed") for item in probe)
    ):
        raise RuntimeError(f"Accessibility audit missed planted failures: {probe}")
    audited = 0
    skipped: set[str] = set()
    for theme in ("light", "dark"):
        if run("document.documentElement.dataset.theme") != theme:
            run("document.querySelector('#theme').click()")
            wait(f"document.documentElement.dataset.theme === '{theme}'")
        for page in PAGES:
            run(f"document.querySelector('[data-page={page}]').click()")
            wait(f"!/Loading|Reading current/.test(document.querySelector('#{page}').textContent)")
            result = run("window.smokeAudit(document.body)")
            if result["failures"]:
                raise RuntimeError(f"Accessibility audit {theme} {page}: {result['failures'][:8]}")
            audited += result["checked"]
            skipped.update(result["skipped"])
        run("document.querySelector('[data-page=parts]').click()")
        wait("document.querySelector('#parts-data [data-part]')")
        run("document.querySelector('#parts-data [data-part]').click()")
        wait("document.querySelector('#drawer-data [data-edit]')")
        result = run("window.smokeAudit(document.querySelector('#drawer'))")
        if result["failures"]:
            raise RuntimeError(f"Accessibility audit {theme} part drawer: {result['failures'][:8]}")
        audited += result["checked"]
        run("document.querySelector('#close-drawer').click()")
        wait("!document.querySelector('#drawer').open")
    print(
        f"Desktop smoke: Ctrl+1–9/Ctrl+K destinations with primary focus, dialog guard, contextual Move/catalog/History state, Python History search/sort and rendered contrast/name audit of {audited} elements on ten pages in both themes passed (unmeasured gradient/image backgrounds: {sorted(skipped) or 'none'}).",
        flush=True,
    )
    return {"audited": audited, "skipped": sorted(skipped)}
