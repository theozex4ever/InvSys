"""Opt-in native smoke probe. Only use it with an explicit disposable database."""

import logging
import time
from typing import Any


class DesktopSmoke:
    def __init__(self) -> None:
        self.error: str | None = None
        self.stock_result: dict[str, Any] | None = None

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
            self._stock_workflows(window, wait)
            print(
                "Desktop smoke: built file assets, real bridge, operator save, catalog and drawer passed.",
                flush=True,
            )
        except Exception as error:
            logging.getLogger(__name__).exception("Desktop smoke failed")
            self.error = str(error)
        finally:
            window.destroy()

    def _stock_workflows(self, window: Any, wait: Any) -> None:
        """Exercise real writes, drafts, review, and lost-response recovery."""

        def run(script: str) -> Any:
            return window.evaluate_js(script)

        def require(script: str, label: str) -> None:
            if not run(script):
                raise RuntimeError(f"Desktop stock smoke failed: {label}")

        run("""
            window.smokeAPI = window.pywebview.api;
            window.smokeAPI.stock_context('DESKTOP-SMOKE').then(r => {
                window.smokeBefore = r.data;
            });
            document.querySelector('[data-page=receive]').click();
        """)
        wait(
            "window.smokeBefore && document.querySelector('#receive-part_number option[value=DESKTOP-SMOKE]')"
        )
        run("""
            document.querySelector('#receive-part_number').value='DESKTOP-SMOKE';
            document.querySelector('#receive-part_number').dispatchEvent(new Event('change'));
        """)
        wait("!document.querySelector('#receive-submit').disabled")
        require(
            "document.querySelector('#receive-location').value === 'Stock'",
            "default location",
        )
        run("""
            document.querySelector('#receive-quantity').value='8';
            document.querySelector('#receive-lot_number').value='SMOKE-A';
            document.querySelector('#receive-reference').value='SMOKE-RECEIVE';
            document.querySelector('#receive-notes').value='Inspected';
            document.querySelector('[data-page=dashboard]').click();
            document.querySelector('[data-page=receive]').click();
        """)
        wait("!document.querySelector('#receive-submit').disabled")
        require(
            "document.querySelector('#receive-quantity').value === '8' && document.querySelector('#receive-lot_number').value === 'SMOKE-A'",
            "receipt draft retention",
        )
        run(
            "document.querySelector('#receive-form').requestSubmit(); document.querySelector('#receive-form').requestSubmit()"
        )
        wait(
            "document.querySelector('#receive-result').textContent.includes('Received 8') && !document.querySelector('#receive-submit').disabled"
        )
        require(
            "document.querySelector('#receive-quantity').value === '' && document.querySelector('#receive-lot_number').value === '' && document.querySelector('#receive-reference').value === '' && document.querySelector('#receive-notes').value === 'Inspected'",
            "receipt repeat-entry reset",
        )
        run("""
            document.querySelector('#receive-quantity').value='12';
            document.querySelector('#receive-lot_number').value='SMOKE-B';
            document.querySelector('#receive-form').requestSubmit();
        """)
        wait(
            "document.querySelector('#receive-result').textContent.includes('Received 12') && !document.querySelector('#receive-submit').disabled"
        )
        run("document.querySelector('[data-page=ship]').click()")
        wait("document.querySelector('#ship-part_number option[value=DESKTOP-SMOKE]')")
        run(
            "document.querySelector('#ship-part_number').value='DESKTOP-SMOKE'; document.querySelector('#ship-part_number').dispatchEvent(new Event('change'))"
        )
        wait("!document.querySelector('#ship-submit').disabled")
        run("""
            window.smokeContext = window.smokeAPI.stock_context;
            window.smokeAPI.stock_context = async part => {
                const result = await window.smokeContext(part);
                return await new Promise(resolve => { window.smokeReleaseContext = () => resolve(result); });
            };
            document.querySelector('#ship-refresh').click();
        """)
        wait("typeof window.smokeReleaseContext === 'function'")
        run("""
            document.querySelector('#operator').value='Desktop smoke edited';
            document.querySelector('#operator').dispatchEvent(new Event('input'));
            window.smokeReleaseContext(); window.smokeAPI.stock_context = window.smokeContext;
        """)
        wait("!document.querySelector('#ship-submit').disabled")
        require(
            "document.querySelector('#ship-review').textContent.includes('DESKTOP-SMOKE')",
            "operator edit preserves pending availability read",
        )
        run(
            "document.querySelector('#operator').value='Desktop smoke'; document.querySelector('#operator').dispatchEvent(new Event('input'))"
        )
        run("""
            document.querySelector('#ship-lot_number').value='SMOKE-A';
            document.querySelector('#ship-quantity').value='2147483647';
            document.querySelector('#ship-recipient').value='Smoke customer';
            document.querySelector('#ship-form').requestSubmit();
        """)
        wait(
            "document.querySelector('#ship-error').textContent.includes('Not enough stock')"
        )
        require(
            "document.querySelector('#ship-recipient').value === 'Smoke customer' && !document.querySelector('#ship-confirmation').open",
            "shortage preserves draft",
        )
        run("""
            document.querySelector('#ship-quantity').value='3';
            document.querySelector('[data-page=parts]').click();
            document.querySelector('[data-page=ship]').click();
        """)
        wait("!document.querySelector('#ship-submit').disabled")
        require(
            "document.querySelector('#ship-quantity').value === '3' && document.querySelector('#ship-lot_number').value === 'SMOKE-A'",
            "ship draft retention",
        )
        run("""
            window.smokePreview = window.smokeAPI.preview_ship;
            window.smokeAPI.preview_ship = async fields => {
                const result = await window.smokePreview(fields);
                return await new Promise(resolve => { window.smokeReleasePreview = () => resolve(result); });
            };
            document.querySelector('#ship-form').requestSubmit();
        """)
        wait("typeof window.smokeReleasePreview === 'function'")
        run("""
            document.querySelector('#operator').value='Desktop smoke edited';
            document.querySelector('#operator').dispatchEvent(new Event('input'));
            window.smokeReleasePreview(); window.smokeReleasePreview = null;
        """)
        wait("!document.querySelector('#ship-submit').disabled")
        require(
            "!document.querySelector('#ship-confirmation').open",
            "operator edit invalidates pending shipment preview",
        )
        run(
            "document.querySelector('#operator').value='Desktop smoke'; document.querySelector('#operator').dispatchEvent(new Event('input'))"
        )
        run("document.querySelector('#ship-form').requestSubmit()")
        wait("typeof window.smokeReleasePreview === 'function'")
        run("""
            document.querySelector('[data-page=dashboard]').click();
            document.querySelector('[data-page=ship]').click();
            window.smokeReleasePreview(); window.smokeAPI.preview_ship = window.smokePreview;
        """)
        wait("!document.querySelector('#ship-submit').disabled")
        require(
            "!document.querySelector('#ship-confirmation').open",
            "late preview invalidated on navigation",
        )
        run("document.querySelector('#ship-form').requestSubmit()")
        wait("document.querySelector('#ship-confirmation').open")
        require(
            "document.querySelector('#ship-confirm-data').textContent.includes('SMOKE-A') && document.querySelector('#ship-confirm-data').textContent.includes('Smoke customer') && document.querySelector('#ship-confirm-data').textContent.includes('Lot remaining')",
            "real shipment confirmation",
        )
        run(
            "document.querySelector('#ship-confirm-submit').click(); document.querySelector('#ship-confirm-submit').click()"
        )
        wait(
            "document.querySelector('#ship-result').textContent.includes('Shipment SHP-')"
        )
        require(
            "document.querySelector('#ship-submit').disabled && !!document.querySelector('#ship-result [data-another]')",
            "explicit ship another",
        )
        run("""
            window.smokeAPI.stock_context('DESKTOP-SMOKE').then(r => { window.smokeAfter = r.data; });
        """)
        wait("window.smokeAfter")
        require(
            "window.smokeAfter.part.quantity === window.smokeBefore.part.quantity + 17 && window.smokeAfter.transactions.length === window.smokeBefore.transactions.length + 3 && window.smokeAfter.shipments.length === window.smokeBefore.shipments.length + 1",
            "one receipt/shipment per double click",
        )

        # Lose a transport response after a real receipt has committed.
        run("""
            window.smokeReceive = window.smokeAPI.receive;
            window.smokeCalls = 0;
            window.smokeAPI.receive = async fields => { window.smokeCalls++; await window.smokeReceive(fields); throw new Error('Lost response'); };
            document.querySelector('[data-page=receive]').click();
        """)
        wait("!document.querySelector('#receive-submit').disabled")
        run("""
            document.querySelector('#receive-quantity').value='2';
            document.querySelector('#receive-lot_number').value='SMOKE-LOST';
            document.querySelector('#receive-form').requestSubmit(); document.querySelector('#receive-form').requestSubmit();
        """)
        wait(
            "document.querySelector('#receive-error').textContent.includes('Completion is uncertain')"
        )
        require(
            "window.smokeCalls === 1 && document.querySelector('#receive-quantity').value === '2' && document.querySelector('#receive-submit').disabled",
            "lost receipt response preserves and blocks draft",
        )
        run("""
            window.smokeAPI.receive = window.smokeReceive;
            document.querySelector('[data-page=parts]').click(); document.querySelector('[data-page=receive]').click();
            document.querySelector('#receive-recovery [data-recovery=read]').click();
        """)
        wait("document.querySelector('#receive-recovery [data-recovery=completed]')")
        require(
            "document.querySelector('#receive-recovery').textContent.includes('SMOKE-LOST')",
            "authoritative receipt reconciliation",
        )
        run(
            "document.querySelector('#receive-recovery [data-recovery=completed]').click()"
        )
        require(
            "!document.querySelector('#receive-submit').disabled && document.querySelector('#receive-quantity').value === ''",
            "verified receipt completion",
        )

        require(
            "document.querySelector('#receive-result').textContent.includes('Verified receipt of 2') && document.querySelector('#receive-result').textContent.includes('Current location stock')",
            "persistent recovered receipt result",
        )

        # Lost response after a real shipment; reconcile without retrying.
        run("""
            document.querySelector('[data-page=ship]').click();
            document.querySelector('#ship-result [data-another]').click();
        """)
        wait("!document.querySelector('#ship-submit').disabled")
        run("""
            document.querySelector('#ship-lot_number').value='SMOKE-B';
            document.querySelector('#ship-quantity').value='1';
            document.querySelector('#ship-recipient').value='Lost response customer';
            document.querySelector('#ship-form').requestSubmit();
        """)
        wait("document.querySelector('#ship-confirmation').open")
        run("""
            window.smokeShip = window.smokeAPI.ship; window.smokeShipCalls = 0;
            window.smokeAPI.ship = async fields => { window.smokeShipCalls++; await window.smokeShip(fields); throw new Error('Lost response'); };
            document.querySelector('#ship-confirm-submit').click(); document.querySelector('#ship-confirm-submit').click();
        """)
        wait(
            "document.querySelector('#ship-error').textContent.includes('Completion is uncertain')"
        )
        require(
            "window.smokeShipCalls === 1 && document.querySelector('#ship-recipient').value === 'Lost response customer'",
            "lost shipment response preserves draft",
        )
        run(
            "window.smokeAPI.ship = window.smokeShip; document.querySelector('#ship-recovery [data-recovery=read]').click()"
        )
        wait("document.querySelector('#ship-recovery [data-recovery=completed]')")
        require(
            "document.querySelector('#ship-recovery').textContent.includes('Lost response customer')",
            "shipment reconciliation exposes number and recipient",
        )
        run(
            "document.querySelector('#ship-recovery [data-recovery=completed]').click()"
        )
        require(
            "document.querySelector('#ship-submit').disabled && !!document.querySelector('#ship-result [data-another]')",
            "verified shipment requires ship another",
        )

        require(
            "document.querySelector('#ship-result').textContent.includes('Verified shipment of 1') && document.querySelector('#ship-result').textContent.includes('SHP-')",
            "persistent recovered shipment number",
        )

        # Failure before sending a mutation: authoritative reads permit explicit unlock.
        run("""
            window.smokeAPI.receive = async () => { throw new Error('Not sent'); };
            document.querySelector('[data-page=receive]').click();
        """)
        wait("!document.querySelector('#receive-submit').disabled")
        run(
            "document.querySelector('#receive-quantity').value='4'; document.querySelector('#receive-lot_number').value='SMOKE-NOT-SENT'; document.querySelector('#receive-form').requestSubmit()"
        )
        wait(
            "document.querySelector('#receive-error').textContent.includes('Completion is uncertain')"
        )
        run(
            "window.smokeAPI.receive = window.smokeReceive; document.querySelector('#receive-recovery [data-recovery=read]').click()"
        )
        wait("document.querySelector('#receive-recovery [data-recovery=absent]')")
        require(
            "document.querySelector('#receive-recovery .recovery-records').textContent.includes('No new audit records')",
            "absent mutation reconciliation",
        )
        run(
            "document.querySelector('#receive-recovery [data-recovery=absent]').click()"
        )
        require(
            "!document.querySelector('#receive-submit').disabled && document.querySelector('#receive-quantity').value === '4'",
            "explicit recovery preserves unsent draft",
        )
        run(
            "window.smokeAPI.stock_context('DESKTOP-SMOKE').then(r => { window.smokeFinal = r.data; });"
        )
        wait("window.smokeFinal")
        self.stock_result = run("window.smokeFinal")
        print(
            "Desktop smoke: receipt repeat entry, drafts, shipment confirmation/shortage, double clicks and transport reconciliation passed.",
            flush=True,
        )
