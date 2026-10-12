"""Native smoke for Adjust Count: real writes, thresholds, drafts and lost responses."""

import json
import time
from typing import Any


def check_adjust(window: Any, wait: Any, part: str) -> dict[str, Any]:
    """Drive the Adjust page against a disposable part; return its final stock context."""
    run = window.evaluate_js

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop adjust smoke failed: {label}")

    def select(name: str, value: str) -> None:
        run(
            f"document.querySelector('#adjust-{name}').value={json.dumps(value)}; document.querySelector('#adjust-{name}').dispatchEvent(new Event('change', {{bubbles: true}}))"
        )

    def enter(counted: int, reason: str) -> None:
        run(f"""
            document.querySelector('#adjust-counted').value='{counted}';
            document.querySelector('#adjust-reason').value={json.dumps(reason)};
            document.querySelector('#adjust-counted').dispatchEvent(new Event('input', {{bubbles: true}}));
        """)

    def balances() -> str:
        run(f"""
            window.smokeAdjustBalances = null;
            window.smokeAPI.stock_context({json.dumps(part)}).then(r => {{ window.smokeAdjustContext = r.data; window.smokeAdjustBalances = Object.fromEntries(r.data.part.balances.map(b => [b.lot_number, b.quantity])); }});
        """)
        wait("window.smokeAdjustBalances")
        return str(run("JSON.stringify(window.smokeAdjustBalances)"))

    # Seed through the public bridge: one populated Lot and one existing zero-stock Lot.
    run(f"""
        window.smokeAPI = window.pywebview.api; window.smokeAdjustReady = false;
        (async () => {{
            const api = window.smokeAPI; const part = {json.dumps(part)};
            await api.create_part({{part_number: part, description: 'Adjust count smoke', minimum_quantity: 0, location: 'Stock'}});
            for (const [lot, quantity] of [['ADJ-A', 25], ['ADJ-ZERO', 1]]) {{
                await api.receive({{part_number: part, quantity, location: 'Stock', lot_number: lot, operator: 'Desktop smoke', reference: '', notes: ''}});
            }}
            await api.adjust_count({{part_number: part, location: 'Stock', lot_number: 'ADJ-ZERO', counted: 0, expected: 1, operator: 'Desktop smoke', reason: 'Zero-stock Lot', confirmed: false}});
            window.smokeAdjustReady = true;
        }})().catch(error => {{ window.smokeAdjustError = String(error); window.smokeAdjustReady = true; }});
        0;
    """)
    wait("window.smokeAdjustReady")
    require("!window.smokeAdjustError", "seed adjust part")
    run("document.querySelector('[data-page=adjust]').click()")
    wait(f"document.querySelector('#adjust-part_number option[value={json.dumps(part)[1:-1]}]')")
    select("part_number", part)
    wait("!document.querySelector('#adjust-submit').disabled")
    require(
        "document.querySelector('#adjust-location').value === 'Stock' && Array.from(document.querySelector('#adjust-lot_number').options).some(o => o.value === 'ADJ-ZERO' && o.textContent.includes('0 in system'))",
        "default location and zero-stock Lot offered",
    )

    # Invalid reason is rejected by Python and preserves the draft.
    select("lot_number", "ADJ-ZERO")
    enter(4, "   ")
    wait("document.querySelector('#adjust-review').textContent.includes('Increase')")
    run("document.querySelector('#adjust-form').requestSubmit()")
    wait("document.querySelector('#adjust-error').textContent.includes('Reason required.')")
    require(
        "document.querySelector('#adjust-counted').value === '4' && !document.querySelector('#adjust-submit').disabled && document.querySelector('#adjust-recovery').hidden",
        "invalid reason preserves draft and does not lock",
    )

    # Found stock in a zero-stock Lot; a double submission records exactly one correction.
    enter(4, "Found on shelf")
    wait("document.querySelector('#adjust-review').textContent.includes('Increase')")
    run(
        "document.querySelector('#adjust-form').requestSubmit(); document.querySelector('#adjust-form').requestSubmit()"
    )
    wait(
        "document.querySelector('#adjust-result').textContent.includes('from 0 to 4') && !document.querySelector('#adjust-submit').disabled"
    )
    require(
        "document.querySelector('#adjust-counted').value === '' && document.querySelector('#adjust-reason').value === '' && document.querySelector('#adjust-lot_number').value === 'ADJ-ZERO' && !document.querySelector('#adjust-confirmation').open",
        "success clears count and reason, keeps selections, no confirmation below threshold",
    )
    if balances() != '{"ADJ-A":25,"ADJ-ZERO":4}':
        raise RuntimeError("Desktop adjust smoke failed: found stock balance")
    require(
        "window.smokeAdjustContext.transactions.filter(tx => tx.tx_type === 'COUNT_CORRECTION' && tx.reference === 'Found on shelf').length === 1",
        "one correction per double submit",
    )

    # A large correction requires confirmation; cancelling records nothing.
    select("lot_number", "ADJ-A")
    enter(5, "Damaged stock")
    wait("document.querySelector('#adjust-review').textContent.includes('Large correction')")
    run("document.querySelector('#adjust-form').requestSubmit()")
    wait("document.querySelector('#adjust-confirmation').open")
    require(
        "document.querySelector('#adjust-confirm-data').textContent.includes('-20')",
        "confirmation shows authoritative difference",
    )
    run("document.querySelector('#adjust-cancel').click()")
    wait(
        "!document.querySelector('#adjust-confirmation').open && document.querySelector('#adjust-error').textContent.includes('cancelled')"
    )
    require("document.querySelector('#adjust-counted').value === '5'", "cancel preserves draft")
    if balances() != '{"ADJ-A":25,"ADJ-ZERO":4}':
        raise RuntimeError("Desktop adjust smoke failed: cancel changed stock")
    run("document.querySelector('#adjust-form').requestSubmit()")
    wait("document.querySelector('#adjust-confirmation').open")
    run("document.querySelector('#adjust-confirm-submit').click()")
    wait("document.querySelector('#adjust-result').textContent.includes('from 25 to 5')")
    if balances() != '{"ADJ-A":5,"ADJ-ZERO":4}':
        raise RuntimeError("Desktop adjust smoke failed: confirmed large correction")

    # Lose the response after a real correction; reconcile without retrying.
    run("""
        window.smokeAdjust = window.smokeAPI.adjust_count; window.smokeAdjustCalls = 0;
        window.smokeAPI.adjust_count = async fields => { window.smokeAdjustCalls++; await window.smokeAdjust(fields); throw new Error('Lost response'); };
    """)
    enter(6, "Lost response recount")
    wait(
        "document.querySelector('#adjust-review').textContent.includes('Increase') && !document.querySelector('#adjust-review').textContent.includes('Reading')"
    )
    run(
        "document.querySelector('#adjust-form').requestSubmit(); document.querySelector('#adjust-form').requestSubmit()"
    )
    wait("document.querySelector('#adjust-error').textContent.includes('Completion is uncertain')")
    require(
        "window.smokeAdjustCalls === 1 && document.querySelector('#adjust-counted').value === '6' && document.querySelector('#adjust-reason').value === 'Lost response recount' && document.querySelector('#adjust-submit').disabled && document.querySelector('#adjust-counted').disabled",
        "lost response preserves and locks draft",
    )
    # Navigation keeps the lock; a failed recovery read keeps it too.
    run("""
        window.smokeAPI.adjust_count = window.smokeAdjust;
        window.smokeContext = window.smokeAPI.stock_context;
        window.smokeAPI.stock_context = async () => { throw new Error('Read lost'); };
        document.querySelector('[data-page=parts]').click(); document.querySelector('[data-page=adjust]').click();
        document.querySelector('#adjust-recovery [data-recovery=read]').click();
    """)
    wait(
        "document.querySelector('#adjust-recovery .recovery-records').textContent.includes('remains uncertain')"
    )
    require(
        "document.querySelector('#adjust-submit').disabled && !document.querySelector('#adjust-recovery [data-recovery=completed]')",
        "failed recovery read keeps the lock",
    )
    run("""
        window.smokeAPI.stock_context = window.smokeContext;
        document.querySelector('#adjust-recovery [data-recovery=read]').click();
    """)
    wait("document.querySelector('#adjust-recovery [data-recovery=completed]')")
    require(
        "document.querySelector('#adjust-recovery .recovery-records').textContent.includes('COUNT_CORRECTION') && document.querySelector('#adjust-recovery .recovery-records').textContent.includes('Lost response recount') && document.querySelector('#adjust-submit').disabled",
        "authoritative count reconciliation",
    )
    run("document.querySelector('#adjust-recovery [data-recovery=completed]').click()")
    wait("!document.querySelector('#adjust-submit').disabled")
    require(
        "document.querySelector('#adjust-result').textContent.includes('Verified count correction') && document.querySelector('#adjust-counted').value === ''",
        "verified completion unlocks and reports",
    )
    if balances() != '{"ADJ-A":6,"ADJ-ZERO":4}':
        raise RuntimeError("Desktop adjust smoke failed: reconciled balance")
    run("document.querySelector('[data-page=dashboard]').click()")
    final: dict[str, Any] = run("window.smokeAdjustContext")
    return final


def adjust_part_name() -> str:
    return f"DESKTOP-ADJUST-{time.time_ns()}"
