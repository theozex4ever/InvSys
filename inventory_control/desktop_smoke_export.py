"""Native CSV acceptance. Only registered by --smoke-check on disposable inventory."""

import csv
from pathlib import Path
from typing import Any, Protocol


class _Wait(Protocol):
    def __call__(self, script: str, *, timeout: float = 20) -> None: ...


def check_exports(window: Any, wait: _Wait) -> list[Path]:
    run = window.evaluate_js
    idle = "document.querySelectorAll('#settings button:disabled').length === 0"

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop export smoke failed: {label}")

    def inventory_read(name: str) -> None:
        run(f"""
            window.{name} = null;
            Promise.all([
                smokeAPI.stock_context('DESKTOP-SMOKE'),
                smokeAPI.stock_context(smokeBOMPart),
                smokeAPI.bom_definition(smokeBOMPart),
                smokeAPI.dashboard()
            ]).then(results => {{ window.{name} = JSON.stringify(results); }});
        """)
        wait(f"window.{name}")

    inventory_read("smokeBeforeExports")
    run("document.querySelector('[data-page=settings]').click()")
    wait(f"document.querySelectorAll('[data-export-kind]').length === 5 && {idle}")
    destination = Path(run("window.smokeSettings.export_dir"))
    run("""
        window.smokeExport = smokeAPI.export_csv;
        window.smokeExportCalls = 0;
        window.smokeExportResponses = [];
        smokeAPI.export_csv = async kind => {
            smokeExportCalls++;
            const response = await smokeExport(kind);
            smokeExportResponses.push(response);
            return await new Promise(resolve => { window.smokeReleaseExport = () => resolve(response); });
        };
        document.querySelector('[data-export-kind=parts]').click();
        document.querySelector('[data-export-kind=parts]').click();
        document.querySelector('[data-export-kind=inventory]').dispatchEvent(new MouseEvent('click', {bubbles:true}));
    """)
    wait("typeof window.smokeReleaseExport === 'function'")
    require("smokeExportCalls === 1", "duplicate or cross-kind click submitted another export")
    run("""
        document.querySelector('[data-page=dashboard]').click();
        document.querySelector('[data-page=settings]').click();
    """)
    wait("document.querySelectorAll('[data-export-kind]:disabled').length === 5")
    require(
        "document.querySelector('#settings-result').textContent.includes('Exporting Parts')",
        "navigation lost the in-flight export feedback",
    )
    run("window.smokeReleaseExport()")
    wait(
        f"document.querySelector('#settings-result').textContent.startsWith('Exported Parts') && {idle}"
    )
    require(
        "document.activeElement.dataset.exportKind === 'parts'",
        "completed export did not restore focus",
    )
    run("""
        smokeAPI.export_csv = async kind => {
            const response = await smokeExport(kind);
            smokeExportResponses.push(response);
            return response;
        };
    """)
    for kind, label in (
        ("inventory", "Inventory"),
        ("transactions", "Transactions"),
        ("shipments", "Shipments"),
        ("bom", "BOM definitions"),
    ):
        run(f"document.querySelector('[data-export-kind={kind}]').click()")
        wait(
            f"document.querySelector('#settings-result').textContent.startsWith('Exported {label}') && {idle}"
        )
        require(
            "document.querySelector('#settings-result').textContent.includes(smokeExportResponses.at(-1).data.path)",
            f"{kind}: result does not show the written file",
        )
    run("smokeAPI.export_csv = window.smokeExport")
    responses = run("window.smokeExportResponses")
    paths = []
    rows_by_kind = {}
    headers = {
        "parts": ["part_number", "description", "default_location", "minimum_quantity", "active"],
        "inventory": [
            "part_number",
            "description",
            "location",
            "lot_number",
            "quantity",
            "minimum_quantity",
        ],
        "transactions": [
            "timestamp",
            "tx_type",
            "part_number",
            "lot_number",
            "quantity_change",
            "location_from",
            "location_to",
            "operator",
            "reference",
            "notes",
        ],
        "shipments": [
            "shipment_number",
            "timestamp",
            "part_number",
            "quantity",
            "recipient",
            "carrier",
            "tracking_number",
            "consumed_components",
        ],
        "bom": ["parent_part_number", "component_part_number", "quantity_per"],
    }
    for response in responses:
        if not response["ok"]:
            raise RuntimeError(f"Desktop export smoke failed: {response}")
        exported = response["data"]
        path = Path(exported["path"])
        if path.parent != destination or not path.is_file():
            raise RuntimeError(f"Export is missing or outside the selected destination: {path}")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            if (
                reader.fieldnames != headers[exported["kind"]]
                or len(rows) != exported["rows_exported"]
            ):
                raise RuntimeError(f"Export headers or row count changed: {path}")
        rows_by_kind[exported["kind"]] = rows
        paths.append(path)
    if len(paths) != 5:
        raise RuntimeError("All five CSV kinds were not exported.")
    if not any(row["part_number"] == "DESKTOP-SMOKE" for row in rows_by_kind["parts"]):
        raise RuntimeError("Parts export does not contain the selected inventory.")
    if not any(row["lot_number"] == "REFRESH" for row in rows_by_kind["inventory"]):
        raise RuntimeError("Inventory export lost Lot trace.")
    if not any(
        row["reference"] == "REFRESH" and row["operator"] == "Other"
        for row in rows_by_kind["transactions"]
    ):
        raise RuntimeError("Transactions export lost audit metadata.")
    shipment = next(
        row
        for row in rows_by_kind["shipments"]
        if row["shipment_number"] == run("window.smokeBOMNumber")
    )
    expected = {
        f"{line['part_number']}|{line['lot_number']}|{line['location']}|{line['quantity']}"
        for line in run("window.smokeBOMFinal.consumed_components")
    }
    if set(shipment["consumed_components"].split(";")) != expected:
        raise RuntimeError("Shipment export lost persisted component snapshots.")
    if not any(
        row["parent_part_number"] == run("window.smokeBOMPart") for row in rows_by_kind["bom"]
    ):
        raise RuntimeError("BOM export lost direct definitions.")

    # A real filesystem failure must remain an error; preserve earlier exports for inspection.
    preserved = destination.with_name("exports-smoke-preserved")
    destination.rename(preserved)
    try:
        destination.write_text("blocked export folder", encoding="utf-8")
        run("document.querySelector('[data-export-kind=inventory]').click()")
        wait(f"document.querySelector('#settings-result [role=alert]') && {idle}")
        require(
            "document.querySelector('#settings-result').textContent.includes('Could not export inventory') && !document.querySelector('#settings-result').textContent.includes('Exported')",
            "file failure fabricated success",
        )
    finally:
        destination.unlink(missing_ok=True)
        preserved.rename(destination)

    run("""
        window.smokeExportCalls = 0;
        smokeAPI.export_csv = async () => { smokeExportCalls++; throw new Error('Lost export response'); };
        document.querySelector('[data-export-kind=parts]').click();
    """)
    wait(
        f"document.querySelector('#settings-result').textContent.includes('Completion is uncertain') && {idle}"
    )
    require(
        "smokeExportCalls === 1 && document.querySelector('#settings-result').textContent.includes('Open the exports folder') && !document.querySelector('#settings-result').textContent.includes('Exported')",
        "uncertain export retried or gave incorrect recovery instructions",
    )
    run(
        "smokeAPI.export_csv = window.smokeExport; document.querySelector('[data-open-folder=exports]').click()"
    )
    from inventory_control.desktop_smoke_windows import folder_wait_seconds

    wait(
        f"document.querySelector('#settings-result').textContent.startsWith('Opened ') && {idle}",
        timeout=folder_wait_seconds(),
    )
    inventory_read("smokeAfterExports")
    require(
        "smokeBeforeExports === smokeAfterExports", "exports changed inventory or audit records"
    )
    print(
        "Desktop smoke: five real CSV files, Lot/audit/component trace, destination, duplicate clicks, navigation and export failures passed.",
        flush=True,
    )
    return paths
