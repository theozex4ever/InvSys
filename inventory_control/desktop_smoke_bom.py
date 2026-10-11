"""Native BOM authoring smoke journey. Only run it against a disposable database."""

import time
from collections.abc import Callable
from typing import Any


def check_bom_authoring(window: Any, wait: Callable[[str], None]) -> dict[str, Any]:
    """Author nested/shared definitions through the real page and bridge; return restart facts."""
    run = window.evaluate_js
    suffix = str(time.time_ns())
    parent, sub, leaf, extra = (
        f"DESKTOP-AUTH-{kind}-{suffix}" for kind in ("PARENT", "SUB", "LEAF", "EXTRA")
    )

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop BOM authoring smoke failed: {label}")

    def api(call: str) -> Any:
        run(
            f"window.smokeValue=undefined; Promise.resolve({call}).then(r=>{{window.smokeValue=r;}});"
        )
        wait("window.smokeValue!==undefined")
        return run("window.smokeValue")

    def definition_text(contains: str) -> str:
        return (
            f"document.querySelector('#bom-definition').textContent.includes('{contains}') && "
            "!document.querySelector('#bom-definition').textContent.includes('Reading')"
        )

    def choose(number: str) -> None:
        run(
            f"document.querySelector('#bom-parent').value='{number}'; document.querySelector('#bom-parent').dispatchEvent(new Event('change'))"
        )
        wait(definition_text(number))

    def submit(component: str, quantity: int) -> None:
        run(
            f"document.querySelector('#bom-component').value='{component}'; document.querySelector('#bom-quantity').value='{quantity}'; document.querySelector('#bom-form').requestSubmit()"
        )

    def rows() -> int:
        return int(
            run(
                "document.querySelectorAll('#bom-definition table')[0]?.querySelectorAll('tbody tr').length ?? 0"
            )
        )

    for number in (parent, sub, leaf, extra):
        created = api(
            f"window.smokeAPI.create_part({{part_number:'{number}', description:'Disposable BOM authoring smoke', minimum_quantity:0, location:'Stock'}})"
        )
        if not created["ok"]:
            raise RuntimeError("Desktop BOM authoring smoke could not create its parts.")
    received = api(
        f"window.smokeAPI.receive({{part_number:'{leaf}', quantity:20, location:'Stock', lot_number:'AUTH', operator:'Desktop smoke', reference:'', notes:''}})"
    )
    if not received["ok"]:
        raise RuntimeError("Desktop BOM authoring smoke could not receive component stock.")

    run("document.querySelector('[data-page=bom]').click()")
    wait(
        f"!document.querySelector('#bom').hidden && document.querySelector('#bom-parent option[value=\"{parent}\"]') !== null"
    )
    require("document.querySelector('#page-name').textContent==='BOM'", "page title")
    choose(parent)
    require(
        "document.querySelector('#bom-definition').textContent.includes('No components')", "empty"
    )

    # Nested and shared definitions: parent -> sub -> leaf and parent -> leaf.
    submit(sub, 2)
    wait(f"document.querySelector('#bom-result').textContent.includes('Added {sub}')")
    run(f"document.querySelector('#bom-definition [data-bom-open=\"{sub}\"]').click()")
    wait(
        f"document.querySelector('#bom-parent').value==='{sub}' && "
        + definition_text("No components")
    )
    submit(leaf, 3)
    wait(f"document.querySelector('#bom-result').textContent.includes('Added {leaf}')")
    run(f"document.querySelector('#bom-definition [data-bom-open=\"{parent}\"]').click()")
    wait(f"document.querySelector('#bom-parent').value==='{parent}' && " + definition_text(sub))
    submit(leaf, 1)
    wait(f"document.querySelector('#bom-result').textContent.includes('Added {leaf}')")
    if rows() != 2:
        raise RuntimeError("Shared leaf did not appear beside the nested assembly.")

    # Adding an existing component updates its quantity instead of duplicating the link.
    run(
        f"document.querySelector('#bom-component').value='{leaf}'; document.querySelector('#bom-component').dispatchEvent(new Event('change', {{bubbles:true}}))"
    )
    require(
        "document.querySelector('#bom-hint').textContent.includes('already on this BOM') && document.querySelector('#bom-submit').textContent==='Update quantity'",
        "existing component hint",
    )
    submit(leaf, 5)
    wait(f"document.querySelector('#bom-result').textContent.includes('Updated {leaf}')")
    if rows() != 2:
        raise RuntimeError("Updating a component duplicated its link.")

    # Rejections keep the draft and leave the definition unchanged.
    submit(parent, 1)
    wait("document.querySelector('#bom-error').textContent.includes('cannot contain itself')")
    require(
        f"document.querySelector('#bom-component').value==='{parent}' && document.querySelector('#bom-quantity').value==='1' && !document.querySelector('#bom-submit').disabled",
        "self-reference draft",
    )
    # The browser blocks a zero quantity before any request is sent.
    run(
        "document.querySelector('#bom-quantity').value='0'; document.querySelector('#bom-form').requestSubmit()"
    )
    require(
        "document.querySelector('#bom-quantity').validity.rangeUnderflow && !document.querySelector('#bom-result').textContent.includes('Added')",
        "zero quantity",
    )
    choose(sub)
    submit(parent, 1)
    wait("document.querySelector('#bom-error').textContent.includes('circular')")
    choose(parent)
    if rows() != 2:
        raise RuntimeError("A rejected change altered the displayed definition.")

    # Removal requires confirmation and refreshes the definition.
    run(f"document.querySelector('[data-bom-remove=\"{leaf}\"]').click()")
    wait(
        f"document.querySelector('#bom-remove').open && document.querySelector('#bom-remove-data').textContent.includes('{leaf}')"
    )
    run("document.querySelector('#bom-remove-cancel').click()")
    require("!document.querySelector('#bom-remove').open", "removal cancel")
    if rows() != 2:
        raise RuntimeError("Cancelling removal changed the definition.")
    run(f"document.querySelector('[data-bom-remove=\"{leaf}\"]').click()")
    wait("document.querySelector('#bom-remove').open")
    run("document.querySelector('#bom-remove-confirm').click()")
    wait(
        f"document.querySelector('#bom-result').textContent.includes('Removed {leaf}') && !document.querySelector('#bom-remove').open"
    )
    if rows() != 1:
        raise RuntimeError("Removal did not refresh the displayed definition.")
    submit(leaf, 2)
    wait(f"document.querySelector('#bom-result').textContent.includes('Added {leaf}')")

    # A double click sends one change.
    run(
        "window.smokeSave=window.smokeAPI.save_bom_component; window.smokeSaveCalls=0; window.smokeAPI.save_bom_component=async r => { window.smokeSaveCalls++; return await window.smokeSave(r); };"
    )
    submit(extra, 1)
    run("document.querySelector('#bom-form').requestSubmit()")
    wait(f"document.querySelector('#bom-result').textContent.includes('Added {extra}')")
    require("window.smokeSaveCalls===1", "duplicate submission suppression")

    # A lost response locks the draft until authoritative read-back and an operator decision.
    run(
        "window.smokeAPI.save_bom_component=async r => { window.smokeSaveCalls++; await window.smokeSave(r); throw new Error('Lost BOM edit response'); };"
    )
    submit(extra, 4)
    wait("document.querySelector('#bom-error').textContent.includes('Completion is uncertain')")
    require(
        "window.smokeSaveCalls===2 && document.querySelector('#bom-submit').disabled && document.querySelector('#bom-quantity').value==='4' && !document.querySelector('#bom-recovery').hidden",
        "uncertain edit lock and preserved draft",
    )
    run(
        "window.smokeDefinition=window.smokeAPI.bom_definition; window.smokeAPI.bom_definition=async () => { throw new Error('Recovery read unavailable'); }; document.querySelector('[data-bom-recovery=read]').click();"
    )
    wait(
        "document.querySelector('#bom-recovery').textContent.includes('Completion remains uncertain')"
    )
    require(
        "document.querySelector('#bom-submit').disabled && !document.querySelector('[data-bom-recovery=applied]')",
        "failed recovery read keeps the lock",
    )
    run(
        "window.smokeAPI.bom_definition=window.smokeDefinition; window.smokeAPI.save_bom_component=window.smokeSave; document.querySelector('[data-bom-recovery=read]').click();"
    )
    wait("document.querySelector('[data-bom-recovery=applied]')")
    require(
        "document.querySelector('#bom-recovery').textContent.includes('Matches the submitted change') && window.smokeSaveCalls===2",
        "authoritative read-back without retry",
    )
    run("document.querySelector('[data-bom-recovery=applied]').click()")
    wait("document.querySelector('#bom-result').textContent.includes('Verified update')")
    require("!document.querySelector('#bom-submit').disabled", "unlock after decision")

    # Remove the unstocked extra component so the shipment review can be ready.
    run(f"document.querySelector('[data-bom-remove=\"{extra}\"]').click()")
    wait("document.querySelector('#bom-remove').open")
    run("document.querySelector('#bom-remove-confirm').click()")
    wait(f"document.querySelector('#bom-result').textContent.includes('Removed {extra}')")

    # Reviewed BOM shipments depend on the definition; edits require a fresh review.
    draft = (
        f"{{part_number:'{parent}', quantity:1, location:'Stock', operator:'Desktop smoke', "
        "recipient:'Authoring customer', carrier:'', tracking:'', reference:''}"
    )
    stale = api(f"window.smokeAPI.preview_bom_ship({draft})")
    if not stale["ok"] or not stale["data"]["plan"]["ready"]:
        raise RuntimeError("Authored BOM did not produce a ready shipment review.")
    submit(leaf, 3)
    wait(f"document.querySelector('#bom-result').textContent.includes('Updated {leaf}')")
    rejected = api(
        f"window.smokeAPI.ship_bom({{...{draft}, review_id:'{stale['data']['review_id']}'}})"
    )
    if rejected["ok"] or rejected["error"]["code"] != "PLAN_CHANGED":
        raise RuntimeError("An edited definition did not require a fresh BOM review.")
    fresh = api(f"window.smokeAPI.preview_bom_ship({draft})")
    shipped = api(
        f"window.smokeAPI.ship_bom({{...{draft}, review_id:'{fresh['data']['review_id']}'}})"
    )
    if not shipped["ok"]:
        raise RuntimeError("A freshly reviewed edited BOM could not ship.")
    number = shipped["data"]["shipment_number"]
    before = api(f"window.smokeAPI.shipment_detail('{number}')")["data"]
    if [c["quantity"] for c in before["consumed_components"]] != [9]:
        raise RuntimeError("Shipment snapshot did not use the edited definition.")

    # Later edits never rewrite the historical component snapshot.
    submit(leaf, 7)
    wait(f"document.querySelector('#bom-result').textContent.includes('Updated {leaf}')")
    run(f"document.querySelector('[data-bom-remove=\"{sub}\"]').click()")
    wait("document.querySelector('#bom-remove').open")
    run("document.querySelector('#bom-remove-confirm').click()")
    wait(f"document.querySelector('#bom-result').textContent.includes('Removed {sub}')")
    after = api(f"window.smokeAPI.shipment_detail('{number}')")["data"]
    if after != before:
        raise RuntimeError("A BOM edit changed a historical shipment snapshot.")
    require("document.documentElement.scrollWidth <= innerWidth", "BOM page overflows horizontally")
    final = api(f"window.smokeAPI.bom_definition('{parent}')")["data"]
    print(
        "Desktop smoke: BOM authoring of nested/shared definitions, update, rejection, removal confirmation, duplicate clicks, lost-response recovery, review invalidation and unchanged snapshots passed.",
        flush=True,
    )
    return {"parent": parent, "definition": final, "shipment": before}
