from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from inventory_control.config import APP_NAME
from inventory_control.ui.views import DashboardView, HistoryView, MoveAdjustView, PartsView, ReceiveView, ShipView
from inventory_control.ui.widgets import ToastManager


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1220, 760)
        self.toast_manager = ToastManager(self)

        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.setCentralWidget(shell)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(230)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(18, 20, 18, 18)
        side.setSpacing(10)
        title = QLabel("Inventory\nControl")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Local MVP")
        subtitle.setObjectName("SidebarSubtle")
        side.addWidget(title)
        side.addWidget(subtitle)
        side.addSpacing(16)

        self.stack = QStackedWidget()
        self.nav_buttons: Dict[str, QPushButton] = {}
        self.views = {
            "dashboard": DashboardView(self.navigate),
            "parts": PartsView(self.toast),
            "receive": ReceiveView(self.toast, self.operator_name),
            "ship": ShipView(self.toast, self.operator_name),
            "move": MoveAdjustView(self.toast, self.operator_name),
            "history": HistoryView(),
        }
        nav = [
            ("dashboard", "Dashboard"),
            ("parts", "Parts"),
            ("receive", "Receive"),
            ("ship", "Ship"),
            ("move", "Move / Adjust"),
            ("history", "History"),
        ]
        for key, text in nav:
            btn = QPushButton(text)
            btn.setObjectName("NavButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda _, k=key: self.navigate(k))
            self.nav_buttons[key] = btn
            side.addWidget(btn)
            self.stack.addWidget(self.views[key])
        side.addStretch()

        self.operator = QLineEdit("Operator")
        self.operator.setPlaceholderText("Operator name")
        self.operator.setMinimumHeight(44)
        op_card = QFrame()
        op_card.setObjectName("Header")
        op_layout = QVBoxLayout(op_card)
        op_layout.setContentsMargins(12, 12, 12, 12)
        op_label = QLabel("Operator")
        op_label.setObjectName("SidebarSubtle")
        op_layout.addWidget(op_label)
        op_layout.addWidget(self.operator)
        side.addWidget(op_card)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 12)
        self.global_search = QLineEdit()
        self.global_search.setPlaceholderText("Use Parts to search current part records")
        self.global_search.setEnabled(False)
        header_layout.addWidget(self.global_search)
        self.status = QLabel("Local mode | In-memory prototype")
        self.status.setObjectName("Muted")
        header_layout.addWidget(self.status)
        content_layout.addWidget(header)
        content_layout.addWidget(self.stack)

        shell_layout.addWidget(self.sidebar)
        shell_layout.addWidget(content)
        self.navigate("dashboard")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.toast_manager.reposition()

    def operator_name(self) -> str:
        return self.operator.text().strip() or "Operator"

    def toast(self, message: str, level: str = "info") -> None:
        self.toast_manager.show(message, level)

    def navigate(self, key: str) -> None:
        keys = list(self.views.keys())
        self.stack.setCurrentIndex(keys.index(key))
        for name, btn in self.nav_buttons.items():
            btn.setProperty("active", name == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

