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
            self._bom_history_workflows(window, wait)
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

    def prepare_bom(self, store: Any) -> None:
        """Prepare existing definitions through InventoryStore in the disposable smoke DB."""
        suffix = str(time.time_ns())
        self.bom_part = f"DESKTOP-BOM-{suffix}"
        self.bom_sub = f"DESKTOP-SUB-{suffix}"
        self.bom_leaf = f"DESKTOP-LEAF-{suffix}"
        for number in (self.bom_part, self.bom_sub, self.bom_leaf):
            store.add_part(number, "Disposable nested BOM smoke", minimum_quantity=20)
        store.add_bom_component(self.bom_part, self.bom_sub, 2)
        store.add_bom_component(self.bom_sub, self.bom_leaf, 3)
        store.add_bom_component(self.bom_part, self.bom_leaf, 1)
        store.receive(self.bom_part, 10, "Stock", "PARENT", "Setup")
        store.receive(self.bom_sub, 10, "Stock", "INTERMEDIATE", "Setup")
        store.receive(self.bom_leaf, 5, "Stock", "A", "Setup")
        store.receive(self.bom_leaf, 15, "Stock", "B", "Setup")
        self.bom_result: dict[str, Any] | None = None

    def _bom_history_workflows(self, window: Any, wait: Any) -> None:
        import json

        run = window.evaluate_js

        def require(script: str, label: str) -> None:
            if not run(script):
                raise RuntimeError(f"Desktop BOM/History smoke failed: {label}")

        run(
            f"window.smokeBOMPart={json.dumps(self.bom_part)}; window.smokeBOMLeaf={json.dumps(self.bom_leaf)};"
        )
        run(
            "document.querySelector('[data-page=ship]').click(); document.querySelector('#ship-result [data-another]').click()"
        )
        wait("!document.querySelector('#ship-submit').disabled")
        run(
            "document.querySelector('#ship-part_number').value=window.smokeBOMPart; document.querySelector('#ship-part_number').dispatchEvent(new Event('change'))"
        )
        wait(
            "!document.querySelector('#ship-submit').disabled && document.querySelector('#ship-lot_number').disabled"
        )
        run(
            "document.querySelector('#ship-quantity').value='3'; document.querySelector('#ship-recipient').value='BOM customer'; document.querySelector('#ship-form').requestSubmit()"
        )
        wait(
            "document.querySelector('#ship-error').textContent.includes('Component shortage')"
        )
        require(
            "!document.querySelector('#ship-confirmation').open && document.querySelector('#ship-review').textContent.includes('Blocked')",
            "shortage does not submit",
        )
        run(
            "document.querySelector('#ship-quantity').value='2'; document.querySelector('#ship-form').requestSubmit()"
        )
        wait("document.querySelector('#ship-confirmation').open")
        require(
            "document.querySelector('#ship-confirm-data').textContent.includes('14') && document.querySelector('#ship-confirm-data').textContent.includes('Leaf lot allocations') && document.querySelectorAll('#ship-confirm-data tbody').item(1).children.length === 2",
            "shared leaf and multiple lots review",
        )
        run(
            "window.smokeAPI.receive({part_number: window.smokeBOMLeaf, quantity:2, location:'Stock', lot_number:'0', operator:'Other', reference:'STALE', notes:''}).then(r=>{window.smokeBOMChanged=r.ok;});"
        )
        wait("window.smokeBOMChanged")
        run(
            "document.querySelector('#ship-confirm-submit').click(); document.querySelector('#ship-confirm-submit').click()"
        )
        wait(
            "document.querySelector('#ship-error').textContent.includes('Allocation changed. Nothing was shipped.') && !document.querySelector('#ship-confirmation').open"
        )
        require(
            "document.querySelector('#ship-quantity').value === '2' && document.querySelector('#ship-recipient').value === 'BOM customer' && document.querySelectorAll('#ship-review tbody').item(1).children.length === 3",
            "stale rejection retains draft and refreshes allocations",
        )
        run(
            "window.smokeAPI.history({query:window.smokeBOMPart,tx_type:'SHIP_BOM'}).then(r=>{window.smokeBOMRejected=r.data.records.length===0;});"
        )
        wait("window.smokeBOMRejected")
        run("document.querySelector('#ship-form').requestSubmit()")
        wait("document.querySelector('#ship-confirmation').open")
        run(
            "document.querySelector('#ship-confirm-submit').click(); document.querySelector('#ship-confirm-submit').click()"
        )
        wait(
            "document.querySelector('#ship-result').textContent.includes('BOM customer') && !document.querySelector('#ship-confirmation').open"
        )
        run(
            "window.smokeBOMNumber=document.querySelector('#ship-result [data-shipment]').dataset.shipment; document.querySelector('#ship-result [data-shipment]').click()"
        )
        wait(
            "document.querySelector('#history-detail').textContent.includes('Persisted component consumption')"
        )
        require(
            "document.querySelector('#history-detail').textContent.includes(window.smokeBOMPart) && document.querySelector('#history-detail tbody').children.length === 3",
            "success immediately exposes persisted snapshots",
        )
        run(
            "document.querySelector('#history-close').click(); document.querySelector('[data-page=history]').click(); document.querySelector('#history-query').value=window.smokeBOMNumber; document.querySelector('#history-query').dispatchEvent(new Event('input'))"
        )
        wait("document.querySelectorAll('#history-data tbody tr').length === 4")
        run(
            "document.querySelector('#history-type').value='BOM_CONSUME'; document.querySelector('#history-type').dispatchEvent(new Event('change'))"
        )
        wait("document.querySelectorAll('#history-data tbody tr').length === 3")
        run(
            "window.smokeHistoryButton=document.querySelector('#history-data [data-history-id]'); window.smokeHistoryButton.focus(); window.smokeHistoryY=scrollY; window.smokeHistoryButton.click()"
        )
        wait(
            "document.querySelector('#history-detail').textContent.includes('BOM_CONSUME')"
        )
        require(
            "document.querySelector('#history-detail').textContent.includes('Desktop smoke') && document.querySelector('#history-detail').textContent.includes('Used by')",
            "read-only record contains operator and notes",
        )
        run(
            "document.querySelector('#history-close').focus(); document.querySelector('#history-drawer').dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}))"
        )
        require(
            "document.querySelector('#history-drawer').contains(document.activeElement)",
            "drawer focus trap",
        )
        run(
            "document.querySelector('#history-drawer').dispatchEvent(new Event('cancel',{cancelable:true})); document.querySelector('#history-drawer').close()"
        )
        require(
            "document.querySelector('#history-query').value===window.smokeBOMNumber && document.querySelector('#history-type').value==='BOM_CONSUME' && document.activeElement===window.smokeHistoryButton && scrollY===window.smokeHistoryY",
            "drawer preserves filters, position and focus",
        )
        run("document.querySelector('[data-page=dashboard]').click()")
        wait("document.querySelector('#dashboard-data [data-history-id]')")
        run(
            "window.smokeDashboardID=document.querySelector('#dashboard-data [data-history-id]').dataset.historyId; document.querySelector('#dashboard-data [data-history-id]').click()"
        )
        wait(
            "document.querySelector('#history-detail').textContent.includes('SHIP_BOM')"
        )
        require(
            "document.querySelector('#history-detail').textContent.includes(window.smokeBOMNumber)",
            "dashboard opens matching history record",
        )
        run(
            "document.querySelector('#history-close').click(); window.smokeAPI.shipment_detail(window.smokeBOMNumber).then(r=>{window.smokeBOMFinal=r.data;});"
        )
        wait("window.smokeBOMFinal")
        self.bom_result = run("window.smokeBOMFinal")
        print(
            "Desktop smoke: BOM shortage, multi-lot review, stale rejection/reconfirmation, snapshots, History search/type/drawer and dashboard links passed.",
            flush=True,
        )
