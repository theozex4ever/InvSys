"""Opt-in native performance probe (ticket #55). Only use it with a disposable database.

Runs inside the real pywebview window (source launch or frozen bundle) against the
large acceptance fixture and times what an operator sees: from the action to a
*painted, usable* result, measured in the page with ``performance.now()`` and two
animation frames after the expected state appears. Every step also asserts the
rendered result against counts read straight from SQLite, so a fast wrong answer is
a failure, and read-only scenarios must leave the database untouched.

Two modes (the second repeats the first's launch measurement and adds the scenarios):

* ``launch``   - report when the initial dashboard is usable, then exit. The runner
  (``scripts/package_perf.py``) times the process from spawn to that marker.
* ``workflow`` - after launch, run P01-P04 with one warm-up and five measured repeats.
"""

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from inventory_control import perf
from inventory_control.bridge import InventoryBridge
from inventory_control.store import InventoryStore

USABLE_MARKER = "INVSYS-PERF-USABLE"
STEP_TIMEOUT_SECONDS = 30
POLL_SECONDS = 0.01

# Installed once per page. ``perfTimed`` runs ``start`` and polls ``ready`` until it holds, then
# requires two animation frames so the result has been laid out and painted; a window that never
# paints is an error at the step's deadline. ``window.perfResult`` carries the result for Python.
HELPERS = r"""
window.P = {
  $: s => document.querySelector(s),
  n: s => document.querySelectorAll(s).length,
  text: s => document.querySelector(s)?.textContent ?? '',
  set: (s, v, ev = 'input') => { const e = document.querySelector(s); e.value = v; e.dispatchEvent(new Event(ev, { bubbles: true })); },
  click: s => document.querySelector(s).click(),
  actionable: e => !!e && !e.disabled && e.getClientRects().length > 0,
  loading: () => /Loading|Connecting/.test(['#dashboard-data', '#parts-data', '#history-data'].map(s => document.querySelector(s)?.textContent ?? '').join(' ')),
};
window.perfMarks = {};
window.perfT0 = 0;
window.perfResult = null;
// Timers run at most once a second in a window that is occluded or in the background (and so does
// pywebview's own polling for bridge answers): the page's visibility is recorded with every step,
// and a hidden page fails the run instead of passing as a slow result.
window.perfYield = fn => setTimeout(fn, 0);
// A result is only "laid out and painted" once two animation frames have followed it. There is
// no shortcut for a renderer that stalls: missing frames fail at the deadline instead of passing.
window.perfFrames = (deadline, done, fail) => {
  let frames = 0;
  requestAnimationFrame(() => { frames = 1; requestAnimationFrame(() => { frames = 2; }); });
  const wait = () => {
    if (frames >= 2) done(frames);
    else if (performance.now() > deadline) fail(frames);
    else window.perfYield(wait);
  };
  wait();
};
window.perfNoFrames = frames => 'no animation frames after the state was reached (' + frames + ' of 2): the window is not painting';
window.perfTimed = (start, ready, timeoutMs) => {
  window.perfResult = null; window.perfMarks = {};
  let settled = false;
  const finish = value => { if (!settled) { settled = true; window.perfResult = JSON.stringify({ visibility: document.visibilityState, ...value }); } };
  window.perfT0 = performance.now();
  const t0 = window.perfT0;
  const painted = now => window.perfFrames(t0 + timeoutMs,
    frames => finish({ ms: performance.now() - t0, ready_ms: now - t0, frames, marks: window.perfMarks }),
    frames => finish({ timeout: true, ms: performance.now() - t0, frames, problem: window.perfNoFrames(frames) }));
  const check = () => {
    if (settled) return;
    let ok = false, problem = '';
    try { ok = !!ready(); } catch (error) { problem = String(error); }
    const now = performance.now();
    if (ok) painted(now);
    else if (now - t0 > timeoutMs) finish({ timeout: true, ms: now - t0, problem });
    else window.perfYield(check);
  };
  try { start(); } catch (error) { finish({ timeout: true, ms: 0, problem: 'start failed: ' + String(error) }); return; }
  check();
};
// Every bridge answer stamps the step in progress, so a step's record separates the Python
// read and transfer (api_ms, the last answer) from the rendering that follows it.
window.perfWrapApi = () => {
  const api = window.pywebview.api;
  for (const name of Object.keys(api)) {
    if (typeof api[name] !== 'function' || api[name].perfWrapped) continue;
    const original = api[name];
    api[name] = async (...args) => {
      const answer = await original.apply(api, args);
      window.perfMarks.api_ms = performance.now() - window.perfT0;
      return answer;
    };
    api[name].perfWrapped = true;
  }
};
window.perfUsableAt = null;
window.perfUsableError = null;
window.perfWatchUsable = (active, parts, timeoutMs = 60000) => {
  window.perfUsableAt = null; window.perfUsableError = null;
  const deadline = performance.now() + timeoutMs;
  const stat = () => Array.from(document.querySelectorAll('#dashboard-data .stat')).find(e => /Active parts/.test(e.textContent));
  const ok = () => !!stat() && stat().querySelector('.stat-value')?.textContent.trim() === String(active)
    && P.n('#parts-data tbody tr') === Math.min(parts, 100) && P.text('#parts-data .table-footer').startsWith(parts + ' parts') && P.n('#history-data tbody tr') === 50 && !P.loading()
    && ['#query', '#operator', '#global-search', '#theme', '#history-query'].every(s => !P.$(s)?.disabled)
    && P.actionable(P.$('[data-page=parts]')) && P.actionable(P.$('[data-page=history]'));
  const poll = () => {
    if (ok()) window.perfFrames(deadline, () => { window.perfUsableAt = performance.now(); }, frames => { window.perfUsableError = window.perfNoFrames(frames); });
    else if (performance.now() > deadline) window.perfUsableError = 'the dashboard never became usable';
    else window.perfYield(poll);
  };
  poll();
};
"""


# The cell text of the confirmation dialog's tables (a line break becomes a newline).
READ_TABLES = r"""JSON.stringify(Array.from(document.querySelectorAll('#ship-confirm-data .table-wrap')).map(
  wrap => Array.from(wrap.querySelectorAll('tbody tr')).map(row => Array.from(row.cells).map(cell => {
    const copy = cell.cloneNode(true);
    copy.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
    return copy.textContent;
  }))))"""


class ProbeError(RuntimeError):
    """A step failed to reach its expected, correct state."""


class PerfProbe:
    def __init__(self, mode: str, output: Path, database: Path) -> None:
        if mode not in ("launch", "workflow"):
            raise ValueError("Performance mode must be launch or workflow.")
        self.mode = mode
        self.output = output
        self.database = database
        self.samples: dict[str, list[dict[str, Any]]] = {}
        self.errors: list[str] = []
        self.environment: dict[str, Any] = {}
        self.usable: dict[str, Any] = {}
        self.truth = perf.fixture_truth(database)
        self.snapshots: dict[str, str] = {}
        self.error: str | None = None
        # Debugging aid: INVSYS_PERF_ONLY=P01,P04 runs just those scenarios.
        self.only = {item for item in os.environ.get("INVSYS_PERF_ONLY", "").split(",") if item}

    # -- plumbing -----------------------------------------------------------------------

    def run(self, window: Any) -> None:
        self._window = window
        try:
            if not window.events.loaded.wait(60):
                raise ProbeError("Desktop assets failed to load.")
            window.evaluate_js(HELPERS)
            self._launch_usable()
            if self.mode == "workflow":
                self._workflow()
        except Exception as error:
            logging.getLogger(__name__).exception("Performance probe failed")
            self.errors.append(f"probe: {error}")
        finally:
            self.error = "; ".join(self.errors) or None
            self._write()
            # Debugging aid: keep the window open so a DevTools client can collect a trace.
            time.sleep(float(os.environ.get("INVSYS_PERF_HOLD", "0")))
            window.destroy()

    def _js(self, script: str) -> Any:
        return self._window.evaluate_js(script)

    def _wait(self, condition: str, what: str, timeout: float = 20) -> None:
        """Untimed settling between measurements."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._js(f"!!({condition})"):
                return
            time.sleep(0.02)
        raise ProbeError(f"Timed out waiting for {what}. {self._state()}")

    def _state(self) -> str:
        return str(
            self._js(
                "JSON.stringify({page: document.querySelector('[aria-current=page]')?.dataset.page, partsRows: P.n('#parts-data tbody tr'), historyRows: P.n('#history-data tbody tr'), loading: P.loading(), "
                "dialogs: Array.from(document.querySelectorAll('dialog[open]')).map(d => d.id), "
                "errors: Array.from(document.querySelectorAll('[id$=-error], #notice')).filter(e => e.textContent.trim()).map(e => e.id + '=' + e.textContent.trim().slice(0, 100)), "
                "regions: ['#parts-data', '#ship-review', '#ship-confirm-data', '#bomx-result'].map(s => s + ': ' + (document.querySelector(s)?.textContent ?? '').slice(0, 160))})"
            )
        )

    def _timed(self, step_id: str, start: str, ready: str, run: int) -> dict[str, Any]:
        """Run ``start`` in the page, wait for ``ready`` and a painted frame; record the time."""
        self._js("window.perfResult = null")
        began = time.monotonic()
        self._js(f"perfTimed(() => {{ {start} }}, () => ({ready}), {STEP_TIMEOUT_SECONDS * 1000})")
        deadline = began + STEP_TIMEOUT_SECONDS + 10
        raw = None
        while time.monotonic() < deadline:
            raw = self._js("window.perfResult")
            if raw:
                break
            time.sleep(POLL_SECONDS)
        external = (time.monotonic() - began) * 1000
        if not raw:
            diagnostics = self._js(
                "typeof perfTimed + ' result=' + String(window.perfResult) + ' focus=' + document.hasFocus() + ' vis=' + document.visibilityState"
            )
            raise ProbeError(
                f"{step_id}: no result after {STEP_TIMEOUT_SECONDS} s ({diagnostics}). {self._state()}"
            )
        result = json.loads(raw)
        if result.get("timeout"):
            raise ProbeError(
                f"{step_id}: expected state not reached ({result.get('problem') or 'condition false'}). "
                f"{self._state()}"
            )
        if result.get("frames") != 2:
            raise ProbeError(
                f"{step_id}: the page reported {result.get('frames')} of 2 animation frames "
                "after the expected state, so the result is not known to be painted."
            )
        if result.get("visibility") != "visible":
            raise ProbeError(
                f"{step_id}: the page was {result.get('visibility')}, not visible: timings would "
                "measure a throttled window. Keep the window unobstructed."
            )
        sample = {
            "run": run,
            "ms": round(result["ms"], 1),
            "ready_ms": round(result["ready_ms"], 1),
            "frames": result["frames"],
            # Python-side wall time around the same step: adds the evaluate/poll overhead.
            "external_ms": round(external, 1),
        }
        if result.get("marks"):
            sample["marks"] = {key: round(value, 1) for key, value in result["marks"].items()}
        self.samples.setdefault(step_id, []).append(sample)
        return sample

    def _repeat(self, name: str, sequence: Any) -> None:
        """One warm-up and the measured repeats of a scenario; a failure ends only that scenario."""
        for run in range(perf.WARMUPS + perf.REPEATS):
            try:
                sequence(run)
            except Exception as error:
                self.errors.append(f"{name} run {run}: {error}")
                logging.getLogger(__name__).exception("Performance scenario %s failed", name)
                self._js("document.querySelectorAll('dialog[open]').forEach(d => d.close())")
                return

    def _write(self) -> None:
        payload = {
            "schema": 1,
            "mode": self.mode,
            "environment": self.environment,
            "truth": self.truth,
            "usable": self.usable,
            "samples": self.samples,
            "snapshots": self.snapshots,
            "errors": self.errors,
        }
        self.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # -- launch (P05) ---------------------------------------------------------------------

    def _launch_usable(self) -> None:
        began = time.monotonic()
        self._js(f"perfWatchUsable({self.truth['active_parts']}, {self.truth['parts']})")
        deadline = began + 60
        while time.monotonic() < deadline:
            if error := self._js("window.perfUsableError"):
                raise ProbeError(f"The dashboard is not usable: {error} {self._state()}")
            if self._js("window.perfUsableAt") is not None:
                break
            time.sleep(POLL_SECONDS)
        else:
            raise ProbeError(f"The dashboard never became usable. {self._state()}")
        # The runner reads the time at which it sees this line.
        print(USABLE_MARKER, flush=True)
        self.usable = {
            "page_ms": round(float(self._js("window.perfUsableAt")), 1),
            "probe_wait_ms": round((time.monotonic() - began) * 1000, 1),
        }
        self.environment = json.loads(
            self._js(
                "JSON.stringify({user_agent: navigator.userAgent, window: innerWidth + 'x' + innerHeight, "
                "pixel_ratio: devicePixelRatio, screen: screen.width + 'x' + screen.height, "
                "reduced_motion: matchMedia('(prefers-reduced-motion: reduce)').matches})"
            )
        )
        # Navigation and input work now: the usability half of "usable".
        self._js("P.click('[data-page=parts]')")
        self._wait("!P.$('#parts').hidden", "Parts navigation")
        self._js("P.$('#query').focus()")
        self._wait("document.activeElement === P.$('#query')", "search input focus")
        self._js("P.click('[data-page=dashboard]')")
        self._wait("!P.$('#dashboard').hidden", "Dashboard navigation")

    # -- workflow (P01-P04) -------------------------------------------------------------

    def _workflow(self) -> None:
        # After the launch measurement: the stamps add a microtask per bridge call.
        self._js("perfWrapApi()")
        before = perf.protected_state(self.database)
        store = InventoryStore(self.database, seed=False)
        bridge = InventoryBridge(store)
        try:
            if not self.only or "P01" in self.only:
                self._parts(bridge)
            if not self.only or "P02" in self.only:
                self._history()
            if not self.only or "P03" in self.only:
                self._review()
            if not self.only or "P04" in self.only:
                self._explorer()
        finally:
            if changed := perf.writes_between(before, perf.protected_state(self.database)):
                self.errors.append(f"read-only scenarios changed the database: {changed}")
            store.engine.dispose()

    def _go(self, page: str) -> None:
        self._js(f"P.click('[data-page={page}]')")
        self._wait(f"!P.$('#{page}').hidden", f"{page} page")

    def _parts(self, bridge: InventoryBridge) -> None:
        truth = self.truth
        low = len(bridge.search_parts({"low_stock": True})["data"])
        top = bridge.search_parts({"sort": "quantity", "descending": True})["data"][0][
            "part_number"
        ]
        if not low or low == truth["parts"]:
            raise ProbeError("The Low stock filter must select some, but not all, Parts.")
        rows = "P.n('#parts-data tbody tr')"
        # The catalog shows 100 rows a page; the footer states the Python-supplied total.
        page_rows = 100

        def shows(total: int, extra: str = "true") -> str:
            return f"{rows} === {min(total, page_rows)} && P.text('#parts-data .table-footer').startsWith('{total} parts') && {extra}"

        full = shows(truth["parts"])

        def sequence(run: int) -> None:
            self._go("parts")
            self._wait(full + " && !P.loading()", "the full catalog")
            self._timed(
                "P01.search",
                "P.set('#query', 'PERF-00999')",
                shows(
                    1,
                    "P.$('#parts-data [data-part]').dataset.part === 'PERF-00999' "
                    "&& (P.$('#parts-data [data-part]').focus(), P.actionable(document.activeElement))",
                ),
                run,
            )
            self._timed(
                "P01.open_part",
                "P.click('#parts-data [data-part=\"PERF-00999\"]')",
                "P.$('#drawer').open && P.text('#drawer-data').includes('PERF-00999') "
                "&& P.text('#drawer-data').includes('Lot balances') && P.$('#drawer').contains(document.activeElement)",
                run,
            )
            self._js("P.click('#close-drawer')")
            self._wait("!P.$('#drawer').open", "the drawer to close")
            self._timed(
                "P01.clear", "P.click('#clear')", f"{full} && P.$('#query').value === ''", run
            )
            self._timed(
                "P01.inactive",
                "P.set('#filter-status', 'inactive', 'change')",
                shows(
                    truth["inactive_parts"], "P.text('#parts-data tbody tr').includes('Inactive')"
                ),
                run,
            )
            self._timed(
                "P01.active",
                "P.set('#filter-status', 'active', 'change')",
                shows(truth["active_parts"], "!P.text('#parts-data').includes('Inactive')"),
                run,
            )
            self._timed(
                "P01.low_stock",
                "P.$('#filter-low').checked = true; P.set('#filter-status', 'all', 'change')",
                shows(low, "P.text('#parts-data').includes('Low stock')"),
                run,
            )
            self._timed(
                "P01.clear_filters",
                "P.click('#clear')",
                f"{full} && !P.$('#filter-low').checked",
                run,
            )
            self._timed(
                "P01.sort",
                "P.$('#descending').checked = true; P.set('#sort', 'quantity', 'change')",
                f"{full} && P.$('#parts-data [data-part]').dataset.part === {json.dumps(top)}",
                run,
            )
            self._timed(
                "P01.next_page",
                "window.perfFirst = P.$('#parts-data [data-part]').dataset.part; P.click('#parts-data [data-pg=\"1\"]')",
                f"{rows} === {page_rows} && P.$('#parts-data [data-part]').dataset.part !== window.perfFirst "
                "&& P.text('#parts-data .table-footer').includes('Page 2 of')",
                run,
            )
            self._js("P.$('#descending').checked = false; P.set('#sort', 'part_number', 'change')")
            self._wait(
                f"{full} && P.$('#parts-data [data-part]').dataset.part !== {json.dumps(top)}",
                "default order",
            )

        self._repeat("P01", sequence)

    def _history(self) -> None:
        reference = "PERF-RECEIPT-050000"
        if perf.reference_count(self.database, reference) != 1:
            raise ProbeError(f"The fixture must hold exactly one {reference} record.")
        rows = "P.n('#history-data tbody tr')"
        # The footer states Python's match count; SQLite supplies the expected one.
        receives = perf.type_count(self.database, "RECEIVE")

        def page(matching: int) -> str:
            footer = (
                f"P.text('#history-data .table-footer').startsWith('{matching} matching records')"
            )
            return f"{rows} === 50 && !P.loading() && {footer}"

        everything = page(self.truth["transactions"])

        def sequence(run: int) -> None:
            self._go("dashboard")
            self._timed(
                "P02.open",
                "P.click('[data-page=history]')",
                f"!P.$('#history').hidden && {everything}",
                run,
            )
            self._timed(
                "P02.search",
                f"P.set('#history-query', {json.dumps(reference)})",
                f"{rows} === 1 && P.text('#history-data tbody').includes({json.dumps(reference)}) "
                "&& P.text('#history-data .table-footer').startsWith('1 matching records')",
                run,
            )
            self._timed(
                "P02.open_record",
                "P.click('#history-data [data-history-id]')",
                f"P.$('#history-drawer').open && P.text('#history-detail').includes({json.dumps(reference)}) "
                "&& P.text('#history-detail').includes('RECEIVE') && P.$('#history-drawer').contains(document.activeElement)",
                run,
            )
            self._js("P.click('#history-close')")
            self._wait("!P.$('#history-drawer').open", "the History drawer to close")
            self._timed(
                "P02.clear",
                "P.click('#history-clear')",
                f"{everything} && P.$('#history-query').value === ''",
                run,
            )
            self._timed(
                "P02.next_page",
                "window.perfFirst = P.$('#history-data [data-history-id]').dataset.historyId; P.click('#history-data [data-history-page=\"1\"]')",
                f"{everything} && P.$('#history-data [data-history-id]').dataset.historyId !== window.perfFirst "
                "&& P.text('#history-filters').includes('Page: 2')",
                run,
            )
            self._timed(
                "P02.type_filter",
                "P.set('#history-type', 'RECEIVE', 'change')",
                f"{page(receives)} && P.text('#history-filters').includes('Type: RECEIVE') "
                "&& Array.from(document.querySelectorAll('#history-data tbody tr')).every(r => r.textContent.includes('RECEIVE'))",
                run,
            )
            self._js("P.click('#history-clear')")
            self._wait(
                everything
                + " && P.$('#history-query').value === '' && P.$('#history-type').value === ''",
                "cleared History",
            )

        self._repeat("P02", sequence)

    def _review(self) -> None:
        confirm = "P.$('#ship-confirmation').open && !P.$('#ship-confirm-submit').disabled"

        def select(run: int, key: str, number: str, bom: bool) -> None:
            self._timed(
                f"P03.select_{key}",
                f"P.set('#ship-part_number', {json.dumps(number)}, 'change')",
                f"P.actionable(P.$('#ship-submit')) && P.text('#ship-review').includes({json.dumps(number)}) "
                f"&& (P.$('#ship-lot_number').closest('.field').hidden === {str(bom).lower()})",
                run,
            )

        def review(run: int, key: str, quantity: int) -> None:
            expected = "P.text('#ship-confirm-data').includes('Reviewed lot impact')"
            if key != "standard":
                # A BOM review shows exactly the expected requirement and Lot allocation rows.
                plan = self._plan(key)
                counts = [len(plan["requirements"]), len(plan["allocations"])]
                expected = (
                    "P.text('#ship-confirm-data').includes('Ready to ship') "
                    "&& JSON.stringify(Array.from(document.querySelectorAll('#ship-confirm-data .table-wrap'))"
                    f".map(wrap => wrap.querySelectorAll('tbody tr').length)) === '{json.dumps(counts, separators=(',', ':'))}'"
                )
            self._js(
                "P.set('#ship-quantity', "
                f"'{quantity}'); P.set('#ship-recipient', 'Performance customer')"
            )
            self._timed(
                f"P03.review_{key}",
                "P.$('#ship-form').requestSubmit()",
                f"{confirm} && {expected}",
                run,
            )
            text = str(self._js("P.$('#ship-confirm-data').innerText"))
            tables = json.loads(str(self._js(READ_TABLES)))
            if run == perf.WARMUPS:
                self.snapshots[f"P03.review_{key}"] = text[:2000]
            self._check_review(key, text, tables)
            self._js("P.click('#ship-cancel')")
            self._wait("!P.$('#ship-confirmation').open", "the review dialog to close")

        def sequence(run: int) -> None:
            self._go("dashboard")
            self._timed(
                "P03.open_ship",
                "P.click('[data-page=ship]')",
                f"!P.$('#ship').hidden && P.n('#ship-part_number option') > {self.truth['parts']} "
                "&& P.text('#ship-review') !== 'Reading current stock…'",
                run,
            )
            select(run, "standard", "STANDARD", False)
            # STANDARD's default Location is Receiving; its lots A and B are in Stock.
            self._js(
                "P.set('#ship-location', 'Stock', 'change'); P.set('#ship-lot_number', 'A', 'change')"
            )
            review(run, "standard", 2)
            select(run, "kit", "KIT", True)
            review(run, "kit", 2)
            select(run, "root", "PERF-ROOT", True)
            review(run, "root", 1)

        self._repeat("P03", sequence)

    def _plan(self, kind: str) -> perf.ExpectedPlan:
        """The review a BOM shipment must show, derived from the BOM rows and stock in SQLite."""
        root, quantity = {"kit": ("KIT", 2), "root": ("PERF-ROOT", 1)}[kind]
        return perf.expected_plan(self.database, root, quantity, "Stock")

    def _check_review(self, kind: str, text: str, tables: list[list[list[str]]]) -> None:
        """The rendered review against stock, BOM and Lot allocation read from SQLite."""
        if kind == "standard":
            # Lot A holds 10 after the baseline shipment of 2; shipping 2 leaves 8.
            patterns = [
                r"Reviewed lot impact",
                r"Stock\s*/\s*A\b",
                r"Before\s+10\s+Shipping\s+2\s+Lot remaining after shipment\s+8\b",
            ]
            differences: list[str] = []
        else:
            plan = self._plan(kind)
            patterns = [
                r"Ready to ship",
                rf"BOM build capacity at this location\s+{plan['buildable']}\b",
            ]
            differences = perf.plan_differences(plan, tables)
        problems = [f"missing {pattern}" for pattern in patterns if not re.search(pattern, text)]
        if problems or differences:
            raise ProbeError(
                f"The {kind} review is wrong: {(problems + differences)[:5]} in {text[:200]!r}"
            )

    def _explorer(self) -> None:
        nodes = "P.n('#bomx-canvas .bomx-node')"
        transform = "P.$('#bomx-canvas').getAttribute('transform')"

        def sequence(run: int) -> None:
            # Start from an empty explorer: a previous graph would satisfy the ready state early.
            self._go("dashboard")
            self._js("P.$('#bomx-part').value = ''; P.$('#bomx-result').innerHTML = ''")
            self._go("bom-explore")
            self._wait("P.n('#bomx-location option') > 0", "Locations")
            self._js(
                "P.set('#bomx-part', 'PERF-ROOT'); P.set('#bomx-location', 'Stock', 'change'); P.set('#bomx-quantity', '1')"
            )
            time.sleep(0.5)  # the part-suggestion lookup is untimed typing, not the explore
            self._wait("P.n('#bomx-parts option') > 0", "part suggestions")
            self._timed(
                "P04.explore",
                "P.$('#bomx-form').requestSubmit()",
                # Once 1,000 nodes and 900 aggregated Leaf rows are laid out, use the graph:
                # the step ends only when the first zoom has been applied and painted.
                f"(() => {{ const M = window.perfMarks; if ({nodes} !== 1000 || P.n('#bomx-result .table-wrap tbody tr') !== 900) return false; "
                "if (!M.rendered) { M.rendered = performance.now() - window.perfT0; window.perfFit = P.text('#bomx-zoom'); P.click('[data-bomx=in]'); return false; } "
                "return P.text('#bomx-zoom') !== window.perfFit; })()",
                run,
            )
            summary = str(self._js("P.$('#bomx-result').innerText"))
            capacity = self._plan("root")["buildable"]
            if (
                "No material shortage" not in summary
                or "900 Leaf materials" not in summary
                or not re.search(rf"{capacity}\s*final builds", summary)
            ):
                raise ProbeError(
                    f"The explorer summary is wrong (capacity {capacity}): {summary[:300]!r}"
                )
            self._timed(
                "P04.zoom",
                f"window.perfPrev = {transform}; P.click('[data-bomx=out]')",
                f"{transform} !== window.perfPrev",
                run,
            )
            self._timed(
                "P04.pan",
                f"window.perfPrev = {transform}; P.$('#bomx-viewport').focus(); "
                "P.$('#bomx-viewport').dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true}))",
                f"{transform} !== window.perfPrev",
                run,
            )
            self._timed(
                "P04.fit",
                f"window.perfPrev = {transform}; P.click('[data-bomx=fit]')",
                f"{transform} !== window.perfPrev && P.text('#bomx-zoom') === window.perfFit",
                run,
            )
            self._timed(
                "P04.select",
                "P.$('#bomx-canvas [data-id=\"500\"]').dispatchEvent(new MouseEvent('click', {bubbles: true}))",
                "P.$('#bomx-canvas [data-id=\"500\"]').getAttribute('aria-pressed') === 'true' "
                "&& P.text('#bomx-inspector').includes(P.$('#bomx-canvas [data-id=\"500\"] .bomx-part').textContent.replace('…', ''))",
                run,
            )

            # Zooming in is where the text of all 1,000 nodes is laid out for the first time.
            self._timed(
                "P04.labels",
                f"window.perfPrev = {transform}; P.click('[data-bomx=reset]')",
                f"{transform} !== window.perfPrev && P.text('#bomx-zoom') === '100%' "
                "&& !P.$('#bomx-canvas').classList.contains('bomx-far') "
                "&& getComputedStyle(P.$('#bomx-canvas .bomx-part')).display !== 'none'",
                run,
            )

        self._repeat("P04", sequence)


def finish_in_process() -> None:  # pragma: no cover - only reachable in the native probe
    """Qt WebEngine can hang during interpreter teardown after the verdict is written."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
