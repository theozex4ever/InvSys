"""Native import probes must finish the dialog before waiting for the bridge."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from inventory_control.desktop_smoke_imports import _ImportSmoke, use_scriptable_file_dialogs


def test_import_selection_retries_when_accept_leaves_the_dialog_open(qapp, tmp_path):
    class LoadingDialog(QFileDialog):
        attempts = 0

        def accept(self):
            self.attempts += 1
            if self.attempts > 1:
                super().accept()

    path = tmp_path / "import.csv"
    path.write_text("part_number,description\nP,Part\n", encoding="utf-8")
    dialog = LoadingDialog(None, "Select CSV", str(tmp_path))
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFile)

    class Window:
        def evaluate_js(self, script):
            dialog.show()

    def wait(script):
        assert not dialog.isVisible(), "Import probe waited before the dialog closed"

    smoke = _ImportSmoke(Window(), wait, tmp_path, "parts", path.name)
    # pytest already runs on the GUI thread; the native probe normally queues here.
    smoke.actions.run = lambda action: action()
    try:
        smoke.select()
        assert dialog.attempts == 2
        assert [Path(selected) for selected in dialog.selectedFiles()] == [path]
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_macos_import_probe_drives_qt_dialogs_instead_of_the_cocoa_panel(qapp):
    attribute = Qt.ApplicationAttribute.AA_DontUseNativeDialogs
    before = qapp.testAttribute(attribute)
    try:
        qapp.setAttribute(attribute, False)
        use_scriptable_file_dialogs(qapp, "linux")
        assert not qapp.testAttribute(attribute)
        use_scriptable_file_dialogs(qapp, "darwin")
        assert qapp.testAttribute(attribute)
    finally:
        qapp.setAttribute(attribute, before)
