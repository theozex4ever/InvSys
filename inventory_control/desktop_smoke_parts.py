"""Native Part edit/active-state smoke checks. Writes only the disposable smoke database."""

import inspect
import time
from typing import Any

PART = "DESKTOP-EDIT"


def check_part_editing(window: Any, smoke_wait: Any) -> None:
    run = window.evaluate_js

    def wait(script: str) -> None:
        try:
            smoke_wait(script)
        except RuntimeError as error:
            line = inspect.stack()[1].lineno
            state = run(
                "document.querySelector('#drawer-data').innerText.slice(0, 300) + ' | ' + document.querySelector('#notice').textContent + ' | dialogs ' + document.querySelectorAll('dialog[open]').length"
            )
            raise RuntimeError(
                f"Part editing smoke step at line {line}: {error} [{state}]"
            ) from error

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Part editing smoke failed: {label}")

    def read_part() -> dict[str, Any]:
        run(
            f"window.smokeEdit=null; window.smokeAPI.part_detail('{PART}').then(r => {{ window.smokeEdit=r; }})"
        )
        wait("window.smokeEdit")
        result: dict[str, Any] = run("window.smokeEdit")
        data: dict[str, Any] = result["data"]
        return data

    run(f"""
        window.smokeEdit = null;
        (async () => {{
            const api = window.smokeAPI;
            const existing = await api.part_detail('{PART}');
            if (!existing.ok) {{
                await api.create_part({{part_number:'{PART}', description:'Edit smoke part', minimum_quantity:2, location:'Stock'}});
                await api.receive({{part_number:'{PART}', quantity:3, location:'Stock', lot_number:'EDIT', operator:'Desktop smoke', reference:'EDIT', notes:''}});
            }}
            // Repeat runs against the same disposable database start from the same catalog values.
            await api.update_part({{part_number:'{PART}', description:'Edit smoke part', minimum_quantity:2, location:'Stock'}});
            await api.set_part_active({{part_number:'{PART}', active:true}});
            window.smokeEdit = true;
        }})();
    """)
    wait("window.smokeEdit")
    run(
        f"""document.querySelector('[data-page=parts]').click();
        document.querySelector('#query').value='{PART}'; document.querySelector('#query').dispatchEvent(new Event('input'));"""
    )
    wait(f"!!document.querySelector('#parts-data [data-part={PART}]')")
    run(f"document.querySelector('#parts-data [data-part={PART}]').click()")
    wait("!!document.querySelector('#drawer-data [data-edit]')")

    # Unsaved edits: Cancel asks first, keeping the editor and the typed values.
    run("document.querySelector('#drawer-data [data-edit]').click()")
    wait("!!document.querySelector('#edit-description')")
    require(
        "document.querySelector('#part-edit').textContent.includes('cannot be changed') && document.querySelector('#part-save').disabled",
        "pristine form has Save disabled",
    )
    # Both themes: the edit form fits and its actions stay reachable at small sizes.
    original_theme = run("document.documentElement.dataset.theme")
    for theme in ("light", "dark"):
        run(
            f"window.pywebview.api.save_theme('{theme}').then(r => {{ if (r.ok) document.documentElement.dataset.theme='{theme}'; }})"
        )
        wait(f"document.documentElement.dataset.theme === '{theme}'")
        for width, height in ((1366, 768), (640, 480)):
            window.resize(width, height)
            time.sleep(0.15)
            run("document.querySelector('#part-cancel').scrollIntoView({block:'nearest'})")
            require(
                "(() => { const d = document.querySelector('#drawer'); const r = document.querySelector('#part-cancel').getBoundingClientRect(); return document.documentElement.scrollWidth <= innerWidth && d.scrollWidth <= d.clientWidth && r.top >= 0 && r.bottom <= innerHeight; })()",
                f"{theme} {width}: edit form fits",
            )
    window.resize(1366, 768)
    run(
        f"window.pywebview.api.save_theme('{original_theme}').then(() => {{ document.documentElement.dataset.theme='{original_theme}'; }})"
    )
    run(
        "document.querySelector('#edit-description').value='Edited by smoke'; document.querySelector('#edit-description').dispatchEvent(new Event('input', {bubbles:true}))"
    )
    run("document.querySelector('#part-cancel').click()")
    wait("document.querySelector('#confirm-dialog').open")
    require(
        "document.activeElement.id === 'confirm-cancel'", "discard prompt focuses the safe action"
    )
    run("document.querySelector('#confirm-cancel').click()")
    wait("!document.querySelector('#confirm-dialog').open")
    require(
        "document.querySelector('#edit-description').value === 'Edited by smoke' && document.querySelector('#drawer').open",
        "keep editing preserves input",
    )
    # Closing the drawer over unsaved work asks too; discarding returns to catalog context.
    run("document.querySelector('#close-drawer').click()")
    wait("document.querySelector('#confirm-dialog').open")
    run("document.querySelector('#confirm-cancel').click()")
    wait("!document.querySelector('#confirm-dialog').open")
    require("document.querySelector('#drawer').open", "drawer stays open after keep editing")
    run("document.querySelector('#part-cancel').click()")
    wait("document.querySelector('#confirm-dialog').open")
    run("document.querySelector('#confirm-accept').click()")
    wait("!!document.querySelector('#drawer-data [data-edit]')")
    require(
        "document.querySelector('#drawer-data').textContent.includes('Edit smoke part')",
        "discard restores saved values",
    )
    if read_part()["description"] != "Edit smoke part":
        raise RuntimeError("Discarded edits were persisted.")

    # Validation comes from Python and preserves the form.
    run("document.querySelector('#drawer-data [data-edit]').click()")
    wait("!!document.querySelector('#edit-description')")
    run(
        "document.querySelector('#edit-location').innerHTML += '<option>Nowhere</option>'; document.querySelector('#edit-location').value='Nowhere'; document.querySelector('#edit-location').dispatchEvent(new Event('input', {bubbles:true})); document.querySelector('#part-edit').requestSubmit()"
    )
    wait("document.querySelector('#part-edit-feedback').textContent.includes('Invalid location')")
    require(
        "!document.querySelector('#edit-description').disabled && document.querySelector('#edit-location').value === 'Nowhere'",
        "rejected edit unlocks and preserves input",
    )

    # Successful save refreshes drawer, catalog and dashboard.
    run("""
        document.querySelector('#edit-location').value='Receiving';
        document.querySelector('#edit-description').value='Edited by smoke';
        document.querySelector('#edit-minimum').value='9';
        document.querySelector('#edit-minimum').dispatchEvent(new Event('input', {bubbles:true}));
        window.smokeUpdates=0; window.smokeUpdate=window.smokeAPI.update_part;
        window.smokeAPI.update_part=async fields => { window.smokeUpdates++; return window.smokeUpdate(fields); };
        document.querySelector('#part-edit').requestSubmit(); document.querySelector('#part-edit').requestSubmit();
    """)
    wait("document.querySelector('#notice').textContent === 'Saved DESKTOP-EDIT.'")
    require("window.smokeUpdates === 1", "duplicate submissions blocked")
    run("window.smokeAPI.update_part=window.smokeUpdate")
    wait(
        f"document.querySelector('#parts-data [data-part={PART}]').closest('tr').textContent.includes('Edited by smoke')"
    )
    require(
        "document.querySelector('#drawer-data').textContent.includes('Receiving') && document.querySelector('#drawer-data').textContent.includes('Edited by smoke')",
        "drawer shows saved part",
    )
    part = read_part()
    if (part["description"], part["minimum_quantity"], part["location"], part["quantity"]) != (
        "Edited by smoke",
        9,
        "Receiving",
        3,
    ):
        raise RuntimeError(f"Edit was not persisted correctly: {part}")

    # Lost response after the write: lock, read back, accept the saved part without retrying.
    run("document.querySelector('#drawer-data [data-edit]').click()")
    wait("!!document.querySelector('#edit-description')")
    run("""
        document.querySelector('#edit-description').value='Lost response edit';
        document.querySelector('#edit-description').dispatchEvent(new Event('input', {bubbles:true}));
        window.smokeUpdates=0;
        window.smokeAPI.update_part=async fields => { window.smokeUpdates++; await window.smokeUpdate(fields); throw new Error('Lost response'); };
        document.querySelector('#part-edit').requestSubmit();
    """)
    wait(
        "document.querySelector('#part-edit-feedback').textContent.includes('may or may not have completed')"
    )
    require(
        "document.querySelector('#edit-description').disabled && document.querySelector('#edit-description').value === 'Lost response edit' && document.querySelector('#part-save').disabled",
        "uncertain save locks preserved input",
    )
    run("""
        window.smokeAPI.update_part=window.smokeUpdate;
        window.smokePartDetail=window.smokeAPI.part_detail;
        window.smokeAPI.part_detail=async () => { throw new Error('Read unavailable'); };
        document.querySelector('#part-recovery [data-recovery=read]').click();
    """)
    wait("document.querySelector('#part-recovery').textContent.includes('still uncertain')")
    require(
        "document.querySelector('#edit-description').disabled && !document.querySelector('#part-recovery [data-decision]')",
        "failed recovery read keeps the lock",
    )
    run(
        "window.smokeAPI.part_detail=window.smokePartDetail; document.querySelector('#part-recovery [data-recovery=read]').click()"
    )
    wait("!!document.querySelector('#part-recovery [data-decision=accept]')")
    require(
        "document.querySelector('#part-recovery').textContent.includes('The change was saved') && window.smokeUpdates === 1",
        "recovery shows persisted save without retrying",
    )
    run("document.querySelector('#part-recovery [data-decision=accept]').click()")
    wait("document.querySelector('#drawer-data').textContent.includes('Lost response edit')")

    # Lost response before the write: operator explicitly resumes the preserved draft.
    run("document.querySelector('#drawer-data [data-edit]').click()")
    wait("!!document.querySelector('#edit-description')")
    run("""
        document.querySelector('#edit-description').value='Never applied';
        document.querySelector('#edit-description').dispatchEvent(new Event('input', {bubbles:true}));
        window.smokeAPI.update_part=async () => { throw new Error('Lost request'); };
        document.querySelector('#part-edit').requestSubmit();
    """)
    wait(
        "document.querySelector('#part-edit-feedback').textContent.includes('may or may not have completed')"
    )
    run(
        "window.smokeAPI.update_part=window.smokeUpdate; document.querySelector('#part-recovery [data-recovery=read]').click()"
    )
    wait("!!document.querySelector('#part-recovery [data-decision=resume]')")
    run("document.querySelector('#part-recovery [data-decision=resume]').click()")
    wait("!document.querySelector('#edit-description').disabled")
    require(
        "document.querySelector('#edit-description').value === 'Never applied' && !document.querySelector('#part-save').disabled",
        "resume restores the preserved draft",
    )
    if read_part()["description"] != "Lost response edit":
        raise RuntimeError("An uncertain, unapplied save changed the part.")
    run("document.querySelector('#part-cancel').click()")
    wait("document.querySelector('#confirm-dialog').open")
    run("document.querySelector('#confirm-accept').click()")
    wait("!!document.querySelector('#drawer-data [data-edit]')")

    # Deactivate a stocked part: confirmation first, Keep active leaves it active.
    run("document.querySelector('#drawer-data [data-active=off]').click()")
    wait("document.querySelector('#confirm-dialog').open")
    require(
        "document.querySelector('#confirm-body').textContent.includes('3 units')",
        "stocked deactivation names the units on hand",
    )
    require(
        "document.activeElement.id === 'confirm-cancel'", "confirmation focuses the safe action"
    )
    # Both themes: the confirmation fits and its actions stay reachable at small sizes.
    previous = run("document.documentElement.dataset.theme")
    for theme in ("light", "dark"):
        run(
            f"window.pywebview.api.save_theme('{theme}').then(r => {{ if (r.ok) document.documentElement.dataset.theme='{theme}'; }})"
        )
        wait(f"document.documentElement.dataset.theme === '{theme}'")
        for width, height in ((1366, 768), (640, 480)):
            window.resize(width, height)
            time.sleep(0.15)
            require(
                "(() => { const d = document.querySelector('#confirm-dialog'); const r = d.querySelector('#confirm-accept').getBoundingClientRect(); return document.documentElement.scrollWidth <= innerWidth && d.scrollWidth <= d.clientWidth && r.top >= 0 && r.bottom <= innerHeight && r.right <= innerWidth; })()",
                f"{theme} {width}: confirmation fits",
            )
    window.resize(1366, 768)
    run(
        f"window.pywebview.api.save_theme('{previous}').then(() => {{ document.documentElement.dataset.theme='{previous}'; }})"
    )
    run("document.querySelector('#confirm-cancel').click()")
    wait("!document.querySelector('#confirm-dialog').open")
    if not read_part()["active"]:
        raise RuntimeError("Declined deactivation changed the part.")
    run("document.querySelector('#drawer-data [data-active=off]').click()")
    wait("document.querySelector('#confirm-dialog').open")
    run("document.querySelector('#confirm-accept').click()")
    wait("document.querySelector('#drawer-data').textContent.includes('Reactivate part')")
    part = read_part()
    if part["active"] or part["quantity"] != 3:
        raise RuntimeError(f"Deactivation lost state or stock: {part}")
    require(
        "document.querySelector('#drawer-data .badge').textContent === 'Inactive'",
        "drawer shows Inactive",
    )
    run("document.querySelector('#drawer-data [data-active=on]').click()")
    wait("document.querySelector('#drawer-data').textContent.includes('Deactivate part')")
    if not read_part()["active"]:
        raise RuntimeError("Reactivation did not persist.")
    # Lost response after a deactivation: the drawer stays closable only through a discard
    # confirmation, a failed recovery read keeps the lock, and nothing is retried.
    run("""
        window.smokeActive=window.smokeAPI.set_part_active; window.smokeActiveCalls=0;
        window.smokeAPI.set_part_active=async fields => {
            const result = await window.smokeActive(fields);
            if (fields.confirm_stock) { window.smokeActiveCalls++; throw new Error('Lost response'); }
            return result;
        };
        document.querySelector('#drawer-data [data-active=off]').click();
    """)
    wait("document.querySelector('#confirm-dialog').open")
    run("document.querySelector('#confirm-accept').click()")
    wait("!!document.querySelector('#part-recovery [data-recovery=read]')")
    run("window.smokeAPI.set_part_active=window.smokeActive")
    run("document.querySelector('#close-drawer').click()")
    wait("document.querySelector('#confirm-dialog').open")
    run("document.querySelector('#confirm-cancel').click()")
    wait("!document.querySelector('#confirm-dialog').open")
    require(
        "document.querySelector('#drawer').open", "uncertain deactivation keeps the drawer open"
    )
    run("""
        window.smokePartDetail=window.smokeAPI.part_detail;
        window.smokeAPI.part_detail=async () => { throw new Error('Read unavailable'); };
        document.querySelector('#part-recovery [data-recovery=read]').click();
    """)
    wait("document.querySelector('#part-recovery').textContent.includes('still uncertain')")
    require(
        "!document.querySelector('#part-recovery [data-decision]')", "failed read keeps the lock"
    )
    run(
        "window.smokeAPI.part_detail=window.smokePartDetail; document.querySelector('#part-recovery [data-recovery=read]').click()"
    )
    wait("!!document.querySelector('#part-recovery [data-decision=accept]')")
    require(
        "document.querySelector('#part-recovery').textContent.includes('The change was saved') && window.smokeActiveCalls === 1",
        "read-back shows the persisted deactivation without retrying",
    )
    run("document.querySelector('#part-recovery [data-decision=accept]').click()")
    wait("document.querySelector('#drawer-data').textContent.includes('Reactivate part')")
    run("document.querySelector('#drawer-data [data-active=on]').click()")
    wait("document.querySelector('#drawer-data').textContent.includes('Deactivate part')")
    # The catalog re-reads after each success; wait for it before checking focus restoration.
    wait(
        f"!!document.querySelector('#parts-data [data-part={PART}]') && document.querySelector('#parts-data tr.selected')"
    )
    run("document.querySelector('#close-drawer').click()")
    # close() clears open before the queued close handler restores catalog focus.
    wait(
        f"!document.querySelector('#drawer').open && document.activeElement.dataset.part === '{PART}'"
    )
    # Hand the catalog back with the search the following smoke steps expect.
    run(
        "document.querySelector('#query').value='DESKTOP-SMOKE'; document.querySelector('#query').dispatchEvent(new Event('input'))"
    )
    wait(
        "!!document.querySelector('#parts-data [data-part=DESKTOP-SMOKE]') && !document.querySelector('#parts-data [data-part=DESKTOP-EDIT]')"
    )
    print(
        "Desktop smoke: part edit in both themes, unsaved-edit confirmation, stocked deactivation, reactivation, duplicate clicks and lost-response recovery passed.",
        flush=True,
    )


def check_part_creation_recovery(window: Any, wait: Any) -> str:
    """Committed and unsent lost responses lock creation until read-back and a decision."""
    run = window.evaluate_js
    suffix = time.time_ns()
    created, unsent = f"DESKTOP-CREATE-{suffix}", f"DESKTOP-UNSENT-{suffix}"

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Part creation smoke failed: {label}")

    def submit_lost(number: str, committed: bool) -> None:
        send = "await window.smokeCreate(part); " if committed else ""
        run("document.querySelector('#add-part').click()")
        wait("document.querySelector('#create-dialog').open")
        run(f"""
            document.querySelector('#number').value = '{number}';
            document.querySelector('#description').value = 'Disposable creation recovery';
            // Minimum 0 keeps this probe out of Low stock and the dashboard's top five.
            document.querySelector('#minimum').value = '0';
            window.smokeAPI.create_part = async part => {{ window.smokeCreateCalls++; {send}throw new Error('Lost response'); }};
            document.querySelector('#new-part').requestSubmit(); document.querySelector('#new-part').requestSubmit();
        """)
        wait("document.querySelector('#create-error').textContent.includes('preserved and locked')")
        require(
            f"document.querySelector('#create-submit').disabled && document.querySelector('#number').value === '{number}'",
            "lost response locks one submission and preserves the form",
        )
        # A failed recovery read keeps the lock and offers no decision.
        run("""
            window.smokeAPI.create_part = window.smokeCreate;
            window.smokeAPI.part_detail = async () => ({ok:false, error:{code:'INTERNAL', message:'Read unavailable'}});
            document.querySelector('#close-create').click();
            document.querySelector('#parts .refresh').click();
        """)
        wait("!document.querySelector('#parts-data').textContent.includes('Loading')")
        run("document.querySelector('#add-part').click()")
        wait("document.querySelector('#create-dialog').open")
        require(
            f"document.querySelector('#create-submit').disabled && !document.querySelector('[data-create-decision]') && document.querySelector('#number').value === '{number}'",
            "failed recovery read keeps the creation lock",
        )
        run("""
            window.smokeAPI.part_detail = window.smokePartRead;
            document.querySelector('#close-create').click();
            document.querySelector('#parts .refresh').click();
        """)
        outcome = "was created" if committed else "was not created"
        wait(f"document.querySelector('#notice').textContent.includes('{number} {outcome}')")
        run("document.querySelector('#add-part').click()")
        wait("document.querySelector('#create-dialog').open")
        require(
            f"document.querySelector('#create-submit').disabled && document.querySelector('[data-create-decision={'created' if committed else 'absent'}]')",
            "authoritative read offers only the matching decision while locked",
        )

    run("""
        window.smokeCreate = window.smokeAPI.create_part; window.smokeCreateCalls = 0;
        window.smokePartRead = window.smokeAPI.part_detail;
        document.querySelector('[data-page=parts]').click();
    """)
    submit_lost(created, committed=True)
    run("document.querySelector('[data-create-decision=created]').click()")
    wait(
        f"!document.querySelector('#create-dialog').open && document.querySelector('#drawer-data').textContent.includes('{created}')"
    )
    run("document.querySelector('#close-drawer').click()")
    wait("!document.querySelector('#drawer').open")
    submit_lost(unsent, committed=False)
    run("document.querySelector('[data-create-decision=absent]').click()")
    require(
        f"!document.querySelector('#create-submit').disabled && document.querySelector('#number').value === '{unsent}'",
        "explicit absence decision unlocks the preserved form",
    )
    run("document.querySelector('#new-part').requestSubmit()")
    wait(f"document.querySelector('#drawer-data').textContent.includes('{unsent}')")
    run("document.querySelector('#close-drawer').click()")
    wait("!document.querySelector('#drawer').open")
    run(
        f"window.smokeCreated = null; Promise.all(['{created}', '{unsent}'].map(n => window.smokeAPI.search_parts({{query:n, status:'all', low_stock:false, sort:'part_number', descending:false}}))).then(r => {{ window.smokeCreated = r.map(x => x.data.length); }})"
    )
    wait("window.smokeCreated")
    require(
        "JSON.stringify(window.smokeCreated) === '[1,1]' && window.smokeCreateCalls === 2",
        "each Part persisted exactly once without automatic retries",
    )
    # Resubmitting an existing number is rejected by Python rather than duplicated.
    run("document.querySelector('#add-part').click()")
    wait("document.querySelector('#create-dialog').open")
    run(f"""
        document.querySelector('#number').value = '{created}';
        document.querySelector('#description').value = 'Duplicate';
        document.querySelector('#new-part').requestSubmit();
    """)
    wait("document.querySelector('#create-error').textContent.includes('Part already exists')")
    run(
        "document.querySelector('#new-part').reset(); document.querySelector('#create-error').textContent = ''; document.querySelector('#close-create').click()"
    )
    print(
        "Desktop smoke: Part creation duplicate click, committed and unsent lost responses, failed recovery read, explicit decisions and duplicate rejection passed.",
        flush=True,
    )
    return created
