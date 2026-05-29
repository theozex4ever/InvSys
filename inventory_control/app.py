import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from inventory_control.ui.main_window import MainWindow
from inventory_control.ui.style import STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()

