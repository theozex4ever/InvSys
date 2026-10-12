"""Native smoke for the Move workflow. Real writes: use a disposable database only."""

from typing import Any

PART = "DESKTOP-MOVE"


def check_move(window: Any, wait: Any) -> None:
    run = window.evaluate_js

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop move smoke failed: {label}")

    def fill(**fields: str) -> None:
        for name, value in fields.items():
            run(
                f"""(() => {{ const e = document.querySelector('#move-{name}'); e.value = {value!r};
                e.dispatchEvent(new Event('input', {{bubbles: true}})); e.dispatchEvent(new Event('change', {{bubbles: true}})); }})()"""
            )

    def balances() -> str:
        # Lot balances and the number of paired movement rows, as read by Python.
        run(
            """window.moveRead = null; window.pywebview.api.stock_context('DESKTOP-MOVE').then(r => {
                const d = r.data; const q = (l, lot) => (d.part.balances.find(b => b.location === l && b.lot_number === lot) || {quantity: 0}).quantity;
                window.moveRead = [q('Stock', 'MOVE-A'), q('Shipping Bench', 'MOVE-A'), d.transactions.filter(t => t.tx_type === 'MOVE_OUT').length, d.transactions.filter(t => t.tx_type === 'MOVE_IN').length].join('|'); })"""
        )
        wait("window.moveRead")
        return str(run("window.moveRead"))

    run("""
        window.moveSetup = null;
        (async () => {
            const api = window.pywebview.api;
            const existing = await api.part_detail('DESKTOP-MOVE');
            if (!existing.ok) {
                const created = await api.create_part({part_number:'DESKTOP-MOVE', description:'Move acceptance', minimum_quantity:0, location:'Stock'});
                if (!created.ok) { window.moveSetup = created; return; }
            }
            window.moveSetup = await api.receive({part_number:'DESKTOP-MOVE', quantity:10, location:'Stock', lot_number:'MOVE-A', operator:'Desktop smoke', reference:'MOVE-SETUP', notes:''});
        })();
    """)
    wait("window.moveSetup")
    require("window.moveSetup.ok", "setup")
    stock0, bench0, out0, in0 = (int(v) for v in balances().split("|"))

    run("document.querySelector('[data-page=move]').click()")
    wait("document.querySelector('#move-part_number option[value=DESKTOP-MOVE]')")
    fill(part_number=PART)
    wait("!document.querySelector('#move-submit').disabled")
    require(
        "document.querySelector('#move-location').value === 'Stock' && document.querySelector('#move-destination').value === 'Shipping Bench'",
        "default source and destination",
    )
    wait("document.querySelector('#move-lot_number option[value=MOVE-A]')")
    fill(lot_number="MOVE-A", quantity="3", reference="MOVE-SMOKE")
    run(
        "document.querySelector('[data-page=dashboard]').click(); document.querySelector('[data-page=move]').click()"
    )
    wait("!document.querySelector('#move-submit').disabled")
    require(
        "document.querySelector('#move-quantity').value === '3' && document.querySelector('#move-lot_number').value === 'MOVE-A' && document.querySelector('#move-reference').value === 'MOVE-SMOKE'",
        "draft retained across navigation",
    )

    fill(destination="Stock")
    run("document.querySelector('#move-form').requestSubmit()")
    wait(
        "document.querySelector('#move-error').textContent.includes('Source and destination cannot match.')"
    )
    require(
        "!document.querySelector('#move-confirmation').open",
        "same-Location rejection has no dialog",
    )
    fill(destination="Shipping Bench")

    # Duplicate clicks create one review and one move.
    run(
        "document.querySelector('#move-form').requestSubmit(); document.querySelector('#move-form').requestSubmit()"
    )
    wait("document.querySelector('#move-confirmation').open")
    require(
        f"Array.from(document.querySelectorAll('#move-confirm-data .review-row strong')).map(e => e.textContent).join('|') === '{stock0}|{stock0 - 3}|{stock0}|{stock0 - 3}|{bench0}|{bench0 + 3}|{bench0}|{bench0 + 3}'",
        "Python before/after quantities for both Locations",
    )
    run(
        "document.querySelector('#move-confirm-submit').click(); document.querySelector('#move-confirm-submit').click()"
    )
    wait("document.querySelector('#move-result').textContent.includes('Moved 3')")
    if balances() != f"{stock0 - 3}|{bench0 + 3}|{out0 + 1}|{in0 + 1}":
        raise RuntimeError("Move must persist balances and exactly one paired record set.")
    require(
        "document.querySelector('#move-quantity').value === '' && document.querySelector('#move-part_number').value === 'DESKTOP-MOVE' && !document.querySelector('#move-submit').disabled",
        "repeat-entry reset keeps selection",
    )

    # A lost response locks the draft; a failed recovery read keeps the lock.
    run("""
        window.moveReal = window.pywebview.api.move;
        window.pywebview.api.move = async request => { await window.moveReal(request); throw new Error('lost'); };
    """)
    fill(quantity="2")
    run("document.querySelector('#move-form').requestSubmit()")
    wait("document.querySelector('#move-confirmation').open")
    run("document.querySelector('#move-confirm-submit').click()")
    wait("!document.querySelector('#move-recovery').hidden")
    run("window.pywebview.api.move = window.moveReal")
    require(
        "document.querySelector('#move-error').textContent.includes('Completion is uncertain') && document.querySelector('#move-submit').disabled && document.querySelector('#move-quantity').disabled && document.querySelector('#move-quantity').value === '2'",
        "ambiguous result locks and preserves the draft",
    )
    run("""
        window.moveContext = window.pywebview.api.stock_context;
        window.pywebview.api.stock_context = async () => ({ok:false, error:{code:'INTERNAL', message:'Read unavailable'}});
        document.querySelector('#move-recovery [data-recovery=read]').click();
    """)
    wait("document.querySelector('#move-recovery').textContent.includes('Read unavailable')")
    require(
        "!document.querySelector('#move-recovery [data-recovery=completed]') && document.querySelector('#move-submit').disabled",
        "failed recovery read keeps the lock",
    )
    run(
        "window.pywebview.api.stock_context = window.moveContext; document.querySelector('#move-recovery [data-recovery=read]').click()"
    )
    wait("!!document.querySelector('#move-recovery [data-recovery=completed]')")
    require(
        "document.querySelector('#move-recovery').textContent.includes('MOVE_IN')",
        "recovery shows audit records",
    )
    run("document.querySelector('#move-recovery [data-recovery=completed]').click()")
    wait(
        "document.querySelector('#move-result').textContent.includes('Verified move') && !document.querySelector('#move-submit').disabled"
    )
    if balances() != f"{stock0 - 5}|{bench0 + 5}|{out0 + 2}|{in0 + 2}":
        raise RuntimeError("The lost-response move must have persisted exactly once.")

    # Another operator drains the lot after review: confirmation is rejected atomically.
    fill(quantity=str(stock0 - 5))
    run("document.querySelector('#move-form').requestSubmit()")
    wait("document.querySelector('#move-confirmation').open")
    run("""
        window.moveStale = null;
        window.pywebview.api.move({part_number:'DESKTOP-MOVE', quantity:1, location:'Stock', destination:'Shipping Bench', lot_number:'MOVE-A', operator:'Other', reference:'MOVE-OTHER'}).then(r => { window.moveStale = r; });
    """)
    wait("window.moveStale")
    run("document.querySelector('#move-confirm-submit').click()")
    wait("document.querySelector('#move-error').textContent.includes('Not enough stock')")
    if balances() != f"{stock0 - 6}|{bench0 + 6}|{out0 + 3}|{in0 + 3}":
        raise RuntimeError("A stale move must be rejected without writes.")

    # Contextual entry from Part details selects the Part and its default source.
    run("""
        document.querySelector('#global-search').click();
        document.querySelector('#query').value='DESKTOP-MOVE';
        document.querySelector('#query').dispatchEvent(new Event('input'));
    """)
    wait("document.querySelector('#parts-data [data-part=DESKTOP-MOVE]')")
    run("document.querySelector('#parts-data [data-part=DESKTOP-MOVE]').click()")
    wait("!!document.querySelector('#drawer-data [data-stock=move]')")
    run("document.querySelector('#drawer-data [data-stock=move]').click()")
    wait(
        "!document.querySelector('#move').hidden && !document.querySelector('#move-submit').disabled"
    )
    require(
        "document.querySelector('#move-part_number').value === 'DESKTOP-MOVE' && document.querySelector('#move-location').value === 'Stock'",
        "contextual Move entry",
    )
    fill(part_number="", quantity="", reference="", lot_number="")
    run("document.querySelector('[data-page=dashboard]').click()")
    print(
        "Desktop smoke: Move draft, review, duplicate clicks, same-Location and stale rejection, lost-response recovery and contextual entry passed.",
        flush=True,
    )
