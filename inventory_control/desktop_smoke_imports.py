"""Parts and Inventory receipt CSV review and recovery through real Qt dialogs."""

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication, QFileDialog

from inventory_control.desktop_smoke_ui import _GuiActions


class _ImportSmoke:
    """Drives one Settings import panel through the real Qt file dialog."""

    def __init__(self, window: Any, wait: Any, directory: Path, kind: str, name: str) -> None:
        self.run = window.evaluate_js
        self.wait = wait
        self.directory = directory
        self.kind = kind
        self.path = directory / name
        self.actions = _GuiActions()
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("Native import smoke requires the Qt application.")
        self.actions.moveToThread(app.thread())

    def q(self, part: str) -> str:
        """Selector for this kind's panel element: review, result, confirm or an action."""
        if part in {"select", "commit", "recover", "resolve"}:
            return f"#{self.kind}-import-actions [data-import={part}]"
        return f"#{self.kind}-import-{part}"

    def el(self, part: str) -> str:
        return f"document.querySelector('{self.q(part)}')"

    def require(self, script: str, label: str) -> None:
        if not self.run(script):
            raise RuntimeError(f"Desktop {self.kind} import smoke failed: {label}")

    def select(self, cancel: bool = False) -> None:
        self.run(f"{self.el('select')}.click()")
        deadline = time.monotonic() + 10
        selected = False

        def finish() -> None:
            nonlocal selected
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QFileDialog) and widget.isVisible():
                    if widget.directory().absolutePath() != str(self.directory):
                        raise RuntimeError(
                            "Import dialog opened outside the selected database folder."
                        )
                    if cancel:
                        widget.reject()
                    else:
                        widget.selectFile(str(self.path))
                        widget.accept()
                    selected = True
                    return

        while not selected and time.monotonic() < deadline:
            self.actions.run(finish)
            time.sleep(0.1)
        if not selected:
            raise RuntimeError("Native import file dialog did not appear.")
        self.wait(f"!{self.el('select')}.disabled")

    def confirm_and_commit(self) -> None:
        self.run(f"{self.el('confirm')}.click(); {self.el('commit')}.click()")

    def lost_response_recovery(self, rows: int) -> None:
        """A lost commit response locks the panel until an explicit recovered decision."""
        self.run(f"""
            window.smokeCommitImport = window.smokeAPI.commit_import;
            window.smokeImportCalls = 0;
            window.smokeAPI.commit_import = async request => {{
                window.smokeImportCalls++;
                await window.smokeCommitImport(request);
                throw new Error('Lost response');
            }};
            {self.el("confirm")}.click();
            {self.el("commit")}.click();
            {self.el("commit")}?.click();
        """)
        self.wait(f"{self.el('result')}.textContent.includes('Completion is uncertain')")
        self.require(
            f"window.smokeImportCalls === 1 && {self.el('select')}.disabled",
            "duplicate and uncertain submission lock",
        )
        for label in ("Recovery unavailable", "Second recovery unavailable"):
            self.run(f"""
                window.smokeImportStatus = window.smokeAPI.import_status;
                window.smokeAPI.import_status = async () => ({{ok:false, error:{{code:'INTERNAL', message:'{label}'}}}});
                {self.el("recover")}.click();
            """)
            self.wait(f"{self.el('result')}.textContent.includes('{label}')")
            self.require(
                f"{self.el('select')}.disabled && !{self.el('resolve')}",
                "failed recovery keeps the lock and clears any prior decision",
            )
            self.run(
                f"window.smokeAPI.import_status = window.smokeImportStatus; {self.el('recover')}.click()"
            )
            self.wait(f"!!{self.el('resolve')}")
            self.require(
                f"{self.el('result')}.textContent.includes('{rows} rows imported')",
                "accurate recovered result",
            )
        self.run(
            f"{self.el('resolve')}.click(); window.smokeAPI.commit_import = window.smokeCommitImport;"
        )


def check_parts_import(window: Any, wait: Any, directory: Path) -> str:
    smoke = _ImportSmoke(window, wait, directory, "parts", "parts-import.csv")
    run, require, select, path, el = smoke.run, smoke.require, smoke.select, smoke.path, smoke.el
    number = f"DESKTOP-IMPORT-{time.time_ns()}"

    run("document.querySelector('[data-page=settings]').click()")
    select(cancel=True)
    wait(f"{el('result')}.textContent.includes('cancelled')")
    path.write_text(f"part_number,description\n{number},\n", encoding="utf-8")
    select()
    require(
        f"{el('review')}.textContent.includes('Description required') && {el('confirm')}.disabled",
        "invalid row and blocked confirmation",
    )
    path.write_text(
        f"part_number,description,minimum_quantity,barcode\n{number},Imported bearing,8,ignored\n",
        encoding="utf-8",
    )
    select()
    require(
        f"{el('review')}.textContent.includes('barcode') && {el('commit')}.disabled",
        "warning and explicit confirmation",
    )
    run(
        "document.querySelector('[data-page=dashboard]').click(); document.querySelector('[data-page=settings]').click()"
    )
    require(
        f"{el('review')}.textContent.includes('parts-import.csv')",
        "review preserved across navigation",
    )
    path.write_text(f"part_number,description\n{number},Changed\n", encoding="utf-8")
    smoke.confirm_and_commit()
    wait(f"{el('result')}.textContent.includes('CSV changed')")
    select()
    smoke.lost_response_recovery(1)
    wait(f"{el('result')}.textContent.includes('Parts import completed')")
    run(
        f"window.smokeAPI.part_detail({json.dumps(number)}).then(r => window.smokeImportedPart = r.data)"
    )
    wait("window.smokeImportedPart")
    require("window.smokeImportedPart.description === 'Changed'", "persisted import")
    # A second review commits an update with a normal response and refreshes cached pages.
    path.write_text(
        f"part_number,description,minimum_quantity\n{number},Reviewed bearing,8\n", encoding="utf-8"
    )
    select()
    smoke.confirm_and_commit()
    wait(f"{el('result')}.textContent.includes('Parts import completed')")
    require(
        "document.querySelector('#dashboard-data').textContent.includes('Reviewed bearing')",
        "dashboard refreshed",
    )
    path.unlink()
    print(
        "Desktop smoke: native import selection/cancellation, row issues, stale file, confirmation, duplicate clicks and lost-response recovery passed.",
        flush=True,
    )
    return number


def check_inventory_import(window: Any, wait: Any, directory: Path, part: str) -> dict[str, Any]:
    """Receipts post through the reviewed lifecycle and refresh Stock, History and dashboard."""
    smoke = _ImportSmoke(window, wait, directory, "inventory", "receipts-import.csv")
    run, require, select, path, el = smoke.run, smoke.require, smoke.select, smoke.path, smoke.el
    lot = f"SMOKE-RCV-{time.time_ns()}"
    header = "part_number,location,lot_number,quantity,reference,notes"

    # Filter History to the new Lot so a refreshed list proves the receipts appeared.
    run(
        f"document.querySelector('[data-page=history]').click(); document.querySelector('#history-query').value={json.dumps(lot)}; document.querySelector('#history-query').dispatchEvent(new Event('input'))"
    )
    wait("!document.querySelector('#history-data').textContent.includes('Connecting')")
    run("document.querySelector('[data-page=settings]').click()")
    select(cancel=True)
    wait(f"{el('result')}.textContent.includes('cancelled')")
    path.write_text(f"{header}\n{part},Stock,,4,PO-SMOKE,\n", encoding="utf-8")
    select()
    require(
        f"{el('review')}.textContent.includes('Lot number required') && {el('confirm')}.disabled",
        "missing Lot is a blocking row error",
    )
    path.write_text(
        f"{header}\n{part},Stock,{lot}-A,4,PO-SMOKE,Dock\n{part},Receiving,{lot}-B,3,,\n",
        encoding="utf-8",
    )
    select()
    require(
        f"{el('review')}.textContent.includes('receipts-import.csv') && {el('commit')}.disabled",
        "explicit confirmation required",
    )
    operator = run("document.querySelector('#operator').value")
    run(
        f"document.querySelector('#operator').value=''; document.querySelector('#operator').dispatchEvent(new Event('input')); {el('confirm')}.click()"
    )
    require(
        f"{el('commit')}.disabled && {el('actions')}.textContent.includes('operator name')",
        "receipts require operator attribution",
    )
    run(
        f"document.querySelector('#operator').value={json.dumps(operator)}; document.querySelector('#operator').dispatchEvent(new Event('input'))"
    )
    require(f"!{el('commit')}.disabled", "operator restores eligibility")
    path.write_text(f"{header}\n{part},Stock,{lot}-A,400,,\n", encoding="utf-8")
    run(f"{el('commit')}.click()")
    wait(f"{el('result')}.textContent.includes('CSV changed')")
    path.write_text(
        f"{header}\n{part},Stock,{lot}-A,4,PO-SMOKE,Dock\n{part},Receiving,{lot}-B,3,,\n",
        encoding="utf-8",
    )
    select()
    smoke.lost_response_recovery(2)
    wait(f"{el('result')}.textContent.includes('Inventory import completed')")
    require(
        f"document.querySelector('#history-data').textContent.includes('{lot}-A') && document.querySelector('#history-data').textContent.includes('{lot}-B')",
        "History refreshed with both receipts",
    )
    require(
        f"document.querySelector('#dashboard-data').textContent.includes({json.dumps(part)})",
        "dashboard activity refreshed",
    )
    run(
        f"window.smokeAPI.stock_context({json.dumps(part)}).then(r => window.smokeReceiptContext = r.data)"
    )
    wait("window.smokeReceiptContext")
    context = run("window.smokeReceiptContext")
    balances = {
        (b["location"], b["lot_number"]): b["quantity"] for b in context["part"]["balances"]
    }
    if balances.get(("Stock", f"{lot}-A")) != 4 or balances.get(("Receiving", f"{lot}-B")) != 3:
        raise RuntimeError(f"Desktop inventory import smoke failed: balances {balances}")
    path.unlink()
    print(
        "Desktop smoke: native receipt import selection/cancellation, Lot errors, operator attribution, stale file, duplicate clicks, lost-response recovery and refreshed Stock/History passed.",
        flush=True,
    )
    return {"part": part, "lot": lot, "context": context}
