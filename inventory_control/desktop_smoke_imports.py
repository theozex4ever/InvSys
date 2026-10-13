"""Parts CSV review and recovery through real Qt file dialogs and the bridge."""

import json
import time
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication, QFileDialog

from inventory_control.desktop_smoke_ui import _GuiActions


def check_parts_import(window: Any, wait: Any, directory: Path) -> str:
    run = window.evaluate_js
    actions = _GuiActions()
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Native import smoke requires the Qt application.")
    actions.moveToThread(app.thread())
    number = f"DESKTOP-IMPORT-{time.time_ns()}"
    path = directory / "parts-import.csv"

    def require(script: str, label: str) -> None:
        if not run(script):
            raise RuntimeError(f"Desktop import smoke failed: {label}")

    def select(cancel: bool = False) -> None:
        run("document.querySelector('[data-import=select]').click()")
        deadline = time.monotonic() + 10
        selected = False

        def finish() -> None:
            nonlocal selected
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QFileDialog) and widget.isVisible():
                    if widget.directory().absolutePath() != str(directory):
                        raise RuntimeError(
                            "Import dialog opened outside the selected database folder."
                        )
                    if cancel:
                        widget.reject()
                    else:
                        widget.selectFile(str(path))
                        widget.accept()
                    selected = True
                    return

        while not selected and time.monotonic() < deadline:
            actions.run(finish)
            time.sleep(0.1)
        if not selected:
            raise RuntimeError("Native import file dialog did not appear.")
        wait("!document.querySelector('[data-import=select]').disabled")

    run("document.querySelector('[data-page=settings]').click()")
    select(cancel=True)
    wait("document.querySelector('#import-result').textContent.includes('cancelled')")
    path.write_text(f"part_number,description\n{number},\n", encoding="utf-8")
    select()
    require(
        "document.querySelector('#import-review').textContent.includes('Description required') && document.querySelector('#import-confirm').disabled",
        "invalid row and blocked confirmation",
    )
    path.write_text(
        f"part_number,description,minimum_quantity,barcode\n{number},Imported bearing,8,ignored\n",
        encoding="utf-8",
    )
    select()
    require(
        "document.querySelector('#import-review').textContent.includes('barcode') && document.querySelector('[data-import=commit]').disabled",
        "warning and explicit confirmation",
    )
    run(
        "document.querySelector('[data-page=dashboard]').click(); document.querySelector('[data-page=settings]').click()"
    )
    require(
        "document.querySelector('#import-review').textContent.includes('parts-import.csv')",
        "review preserved across navigation",
    )
    path.write_text(f"part_number,description\n{number},Changed\n", encoding="utf-8")
    run(
        "document.querySelector('#import-confirm').click(); document.querySelector('[data-import=commit]').click()"
    )
    wait("document.querySelector('#import-result').textContent.includes('CSV changed')")
    select()
    run("""
        window.smokeCommitImport = window.smokeAPI.commit_import;
        window.smokeImportCalls = 0;
        window.smokeAPI.commit_import = async request => {
            window.smokeImportCalls++;
            await window.smokeCommitImport(request);
            throw new Error('Lost response');
        };
        document.querySelector('#import-confirm').click();
        document.querySelector('[data-import=commit]').click();
        document.querySelector('[data-import=commit]')?.click();
    """)
    wait("document.querySelector('#import-result').textContent.includes('Completion is uncertain')")
    require(
        "window.smokeImportCalls === 1 && document.querySelector('[data-import=select]').disabled",
        "duplicate and uncertain submission lock",
    )
    run("""
        window.smokeImportStatus = window.smokeAPI.import_status;
        window.smokeAPI.import_status = async () => ({ok:false, error:{code:'INTERNAL', message:'Recovery unavailable'}});
        document.querySelector('[data-import=recover]').click();
    """)
    wait("document.querySelector('#import-result').textContent.includes('Recovery unavailable')")
    require(
        "document.querySelector('[data-import=select]').disabled && !document.querySelector('[data-import=resolve]')",
        "failed recovery keeps lock",
    )
    run(
        "window.smokeAPI.import_status = window.smokeImportStatus; document.querySelector('[data-import=recover]').click()"
    )
    wait("document.querySelector('[data-import=resolve]')")
    require(
        "document.querySelector('#import-result').textContent.includes('1 rows imported')",
        "accurate recovered result",
    )
    run("""
        window.smokeAPI.import_status = async () => ({ok:false, error:{code:'INTERNAL', message:'Second recovery unavailable'}});
        document.querySelector('[data-import=recover]').click();
    """)
    wait(
        "document.querySelector('#import-result').textContent.includes('Second recovery unavailable')"
    )
    require(
        "document.querySelector('[data-import=select]').disabled && !document.querySelector('[data-import=resolve]')",
        "a failed repeat read clears the prior decision",
    )
    run(
        "window.smokeAPI.import_status = window.smokeImportStatus; document.querySelector('[data-import=recover]').click()"
    )
    wait("document.querySelector('[data-import=resolve]')")
    run(
        "document.querySelector('[data-import=resolve]').click(); window.smokeAPI.commit_import = window.smokeCommitImport;"
    )
    wait("document.querySelector('#import-result').textContent.includes('Parts import completed')")
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
    run(
        "document.querySelector('#import-confirm').click(); document.querySelector('[data-import=commit]').click()"
    )
    wait("document.querySelector('#import-result').textContent.includes('Parts import completed')")
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
