"""Opt-in native smoke probe. Only use it with an explicit disposable database."""

import logging
import time
from typing import Any


class DesktopSmoke:
    def __init__(self) -> None:
        self.error: str | None = None

    def run(self, window: Any) -> None:
        def wait(script: str) -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if window.evaluate_js(script):
                    return
                time.sleep(0.1)
            raise RuntimeError(f"Desktop smoke timed out: {script}")

        try:
            if not window.events.loaded.wait(20):
                raise RuntimeError("Desktop assets failed to load.")
            wait(
                "document.querySelector('#dashboard-data').textContent.includes('Active parts')"
            )
            if window.evaluate_js("location.protocol") != "file:":
                raise RuntimeError("Assets did not load from file://.")
            if not window.evaluate_js("document.styleSheets.length > 0"):
                raise RuntimeError("Built CSS failed to load.")
            window.evaluate_js(
                "document.querySelector('#operator').value='Desktop smoke'; document.querySelector('#operator-form').requestSubmit()"
            )
            wait("document.querySelector('#notice').textContent === 'Operator saved.'")
            window.evaluate_js(
                "document.querySelector('#global-search').click(); document.querySelector('#query').value='DESKTOP-SMOKE'; document.querySelector('#query').dispatchEvent(new Event('input'))"
            )
            wait(
                "!document.querySelector('#parts-data').textContent.includes('Loading')"
            )
            exists = window.evaluate_js(
                "!!document.querySelector('[data-part=\"DESKTOP-SMOKE\"]')"
            )
            if not exists:
                window.evaluate_js(
                    "document.querySelector('#add-part').click(); document.querySelector('#number').value='DESKTOP-SMOKE'; document.querySelector('#description').value='Disposable desktop smoke part'; document.querySelector('#minimum').value='5'; document.querySelector('#new-part').requestSubmit()"
                )
            else:
                window.evaluate_js(
                    "document.querySelector('[data-part=\"DESKTOP-SMOKE\"]').click()"
                )
            wait(
                "document.querySelector('#drawer-data').textContent.includes('DESKTOP-SMOKE')"
            )
            window.evaluate_js("document.querySelector('#close-drawer').click()")
            if not window.evaluate_js(
                "document.documentElement.scrollWidth <= innerWidth"
            ):
                raise RuntimeError("Desktop page overflows horizontally.")
            print(
                "Desktop smoke: built file assets, real bridge, operator save, catalog and drawer passed.",
                flush=True,
            )
        except Exception as error:
            logging.getLogger(__name__).exception("Desktop smoke failed")
            self.error = str(error)
        finally:
            window.destroy()
