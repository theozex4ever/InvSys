"""Native Qt keyboard and viewport checks for the opt-in disposable-data smoke."""

import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


class _GuiActions(QObject):
    requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.finished = threading.Event()
        self.requested.connect(self.perform, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def perform(self) -> None:
        try:
            self.action()
        except Exception as error:
            self.error = error
        finally:
            self.finished.set()

    def run(self, action: Any) -> None:
        # pywebview runs smoke on a worker; Qt keys/captures need the GUI thread.
        self.action = action
        self.error = None
        self.finished.clear()
        self.requested.emit()
        if not self.finished.wait(10):
            raise RuntimeError("Native keyboard/capture action timed out.")
        if self.error:
            raise self.error


def check_ui(window: Any, wait: Any, captures: Path, bom_part: str) -> None:
    import json

    captures.mkdir(parents=True, exist_ok=True)
    run = window.evaluate_js
    actions = _GuiActions()
    actions.moveToThread(QApplication.instance().thread())

    def activate() -> None:
        window.native.raise_()
        window.native.activateWindow()
        QApplication.setActiveWindow(window.native)
        window.native.webview.setFocus(Qt.FocusReason.OtherFocusReason)

    actions.run(activate)
    wait("document.hasFocus()")

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop UI smoke failed: {label}")

    def key(code: Any, modifiers: Any = Qt.KeyboardModifier.NoModifier) -> None:
        actions.run(
            lambda: QTest.keyClick(window.native.webview.focusProxy(), code, modifiers)
        )

    def capture(target: Path) -> None:
        # Geometry updates precede Chromium painting; capture the completed frame.
        run(
            "window.smokePainted=false; requestAnimationFrame(() => requestAnimationFrame(() => { window.smokePainted=true; }));"
        )
        wait("window.smokePainted")
        actions.run(lambda: window.native.webview.grab().save(str(target)))
        if not target.is_file() or not target.stat().st_size:
            raise RuntimeError(f"Native capture failed: {target}")

    def trap(dialog_id: str) -> None:
        run(f"""
            window.smokeDialog = document.querySelector('#{dialog_id}');
            window.smokeControls = Array.from(smokeDialog.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)')).filter(e => e.getClientRects().length);
            smokeControls.at(-1).focus();
        """)
        key(Qt.Key.Key_Tab)
        wait("document.activeElement === smokeControls[0]")
        require(
            "getComputedStyle(document.activeElement).outlineStyle !== 'none'",
            f"visible keyboard focus: {run('({active:document.activeElement.id, focused:document.hasFocus(), visible:document.activeElement.matches(":focus-visible"), outline:getComputedStyle(document.activeElement).outline})')}",
        )
        key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        wait("document.activeElement === smokeControls.at(-1)")
        key(Qt.Key.Key_Escape)
        wait(f"!document.querySelector('#{dialog_id}').open")

    def capture_dialog(dialog_id: str) -> None:
        for theme in ("light", "dark"):
            # Modal dialogs make the shell's theme button inert.
            run(
                f"window.pywebview.api.save_theme('{theme}').then(r => {{ if(r.ok) document.documentElement.dataset.theme='{theme}'; }});"
            )
            wait(f"document.documentElement.dataset.theme === '{theme}'")
            for width, height in ((1366, 768), (1920, 1080), (800, 650), (640, 480)):
                window.resize(width, height)
                time.sleep(0.15)
                require(
                    "document.documentElement.scrollWidth <= innerWidth",
                    f"{dialog_id}: page width",
                )
                require(
                    f"document.querySelector('#{dialog_id}').scrollWidth <= document.querySelector('#{dialog_id}').clientWidth",
                    f"{dialog_id}: dialog width",
                )
                run(
                    f"document.querySelector('#{dialog_id}').scrollTop = document.querySelector('#{dialog_id}').scrollHeight"
                )
                run(
                    f"Array.from(document.querySelectorAll('#{dialog_id} button')).filter(e => e.getClientRects().length).at(-1).scrollIntoView({{block:'nearest'}})"
                )
                require(
                    f"Array.from(document.querySelectorAll('#{dialog_id} button')).filter(e => e.getClientRects().length).slice(-1).every(e => e.getBoundingClientRect().top >= 0 && e.getBoundingClientRect().bottom <= innerHeight)",
                    f"{dialog_id}: last action reachable by scrolling",
                )
                target = captures / f"{dialog_id}-{theme}-{width}.png"
                capture(target)
        window.resize(1366, 768)

    # Capture every enabled page with real data, in both remembered themes.
    for theme in ("light", "dark"):
        if run("document.documentElement.dataset.theme") != theme:
            run("document.querySelector('#theme').click()")
            wait(f"document.documentElement.dataset.theme === '{theme}'")
        for width, height in ((1366, 768), (1920, 1080), (800, 650), (640, 480)):
            window.resize(width, height)
            time.sleep(0.15)
            for page in ("dashboard", "parts", "receive", "ship", "history"):
                run(f"document.querySelector('[data-page={page}]').click()")
                wait(
                    f"!document.querySelector('#{page}').textContent.includes('Loading') && !document.querySelector('#{page}').textContent.includes('Reading current stock')"
                )
                require(
                    "document.documentElement.scrollWidth <= innerWidth",
                    f"{theme} {width} {page}: horizontal page overflow",
                )
                require(
                    f"Array.from(document.querySelectorAll('#{page} input, #{page} select')).filter(e => e.getClientRects().length).every(e => e.labels.length > 0)",
                    f"{page}: persistent form labels",
                )
                run("window.scrollTo(0, document.documentElement.scrollHeight)")
                require(
                    f"Array.from(document.querySelectorAll('#{page} button')).filter(e => e.getClientRects().length && !e.closest('.table-wrap')).every(e => e.getBoundingClientRect().left >= 0 && e.getBoundingClientRect().right <= innerWidth)",
                    f"{theme} {width} {page}: reachable actions outside scrolling tables",
                )
                run("window.scrollTo(0,0)")
                target = captures / f"{page}-{theme}-{width}.png"
                capture(target)

    window.resize(1366, 768)
    run("document.querySelector('[data-page=parts]').click()")
    wait("document.querySelector('#parts-data [data-part=DESKTOP-SMOKE]')")
    run("""
        window.smokePartOrigin = document.querySelector('#parts-data [data-part=DESKTOP-SMOKE]');
        smokePartOrigin.focus(); window.smokePartY = scrollY; smokePartOrigin.click();
    """)
    wait("document.querySelector('#drawer-data [data-part-history]')")
    capture_dialog("drawer")
    trap("drawer")
    wait("document.activeElement === smokePartOrigin && scrollY === smokePartY")
    require(
        "document.activeElement === smokePartOrigin && scrollY === smokePartY",
        "part drawer restores origin and position",
    )
    run("document.querySelector('#add-part').click()")
    capture_dialog("create-dialog")
    trap("create-dialog")
    wait("document.activeElement.id === 'add-part'")

    # Standard/BOM review dialogs have the same controls. Exercise real BOM data.
    run(
        "document.querySelector('[data-page=ship]').click(); document.querySelector('#ship-result [data-another]').click()"
    )
    wait("!document.querySelector('#ship-submit').disabled")
    run(
        f"document.querySelector('#ship-part_number').value={json.dumps(bom_part)}; document.querySelector('#ship-part_number').dispatchEvent(new Event('change'))"
    )
    wait("!document.querySelector('#ship-submit').disabled")
    run(
        "document.querySelector('#ship-quantity').value='1'; document.querySelector('#ship-recipient').value='Keyboard review'; document.querySelector('#ship-form').requestSubmit()"
    )
    wait("document.querySelector('#ship-confirmation').open")
    capture_dialog("ship-confirmation")
    trap("ship-confirmation")
    wait("document.activeElement.id === 'ship-submit'")

    window.resize(1366, 768)
    run("document.querySelector('[data-page=history]').click()")
    wait("document.querySelector('#history-data [data-history-id]')")
    run(
        "window.smokeHistoryOrigin=document.querySelector('#history-data [data-history-id]'); smokeHistoryOrigin.focus(); window.smokeHistoryY=scrollY; smokeHistoryOrigin.click()"
    )
    wait("document.querySelector('#history-detail').textContent.includes('Timestamp')")
    capture_dialog("history-drawer")
    trap("history-drawer")
    wait("document.activeElement === smokeHistoryOrigin && scrollY === smokeHistoryY")
    require(
        "document.activeElement === smokeHistoryOrigin && scrollY === smokeHistoryY",
        "History restores origin and position",
    )

    if run("matchMedia('(prefers-reduced-motion: reduce)').matches"):
        require(
            "getComputedStyle(document.querySelector('.nav-button')).transitionDuration === '0s'",
            "reduced motion disables transitions",
        )
        print("Desktop smoke: native reduced-motion preference passed.", flush=True)
    else:
        print(
            "Desktop smoke: reduced-motion preference inactive; rerun with QTWEBENGINE_CHROMIUM_FLAGS=--force-prefers-reduced-motion to exercise it.",
            flush=True,
        )
    print(
        "Desktop smoke: both themes, five pages at four sizes, labels/reachable actions, native Tab/Shift+Tab/Escape and focus restoration passed.",
        flush=True,
    )
