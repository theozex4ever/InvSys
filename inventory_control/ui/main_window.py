from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
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
from inventory_control.store import STORE
from inventory_control.ui.views import (
    BOMView,
    DashboardView,
    HistoryView,
    MoveAdjustView,
    PartsView,
    ReceiveView,
    SettingsView,
    ShipView,
)
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
            "dashboard": DashboardView(self.navigate, self.open_part, self.open_history),
            "parts": PartsView(self.toast),
            "bom": BOMView(self.toast),
            "receive": ReceiveView(self.toast, self.operator_name),
            "ship": ShipView(self.toast, self.operator_name),
            "move": MoveAdjustView(self.toast, self.operator_name),
            "history": HistoryView(),
            "settings": SettingsView(self.toast, self.operator_name),
        }
        nav = [
            ("dashboard", "Dashboard"),
            ("parts", "Parts"),
            ("bom", "BOM"),
            ("receive", "Receive"),
            ("ship", "Ship"),
            ("move", "Move / Adjust"),
            ("history", "History"),
            ("settings", "Settings"),
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

        self.operator = QLineEdit(STORE.get_setting("last_operator"))
        self.operator.setPlaceholderText("Operator name")
        self.operator.setMinimumHeight(44)
        self.operator.setAccessibleName("Active operator name")
        self.operator.textChanged.connect(self._operator_changed)
        self.operator.editingFinished.connect(self._save_operator)
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
        self.global_search.setPlaceholderText("Search parts by number or description (Ctrl+K)")
        self.global_search.setAccessibleName("Global part search")
        self.global_search.setClearButtonEnabled(True)
        self.global_search.returnPressed.connect(self._submit_global_search)
        header_layout.addWidget(self.global_search)
        self.status = QLabel("Local mode | SQLite")
        self.status.setObjectName("Muted")
        header_layout.addWidget(self.status)
        content_layout.addWidget(header)
        content_layout.addWidget(self.stack)

        shell_layout.addWidget(self.sidebar)
        shell_layout.addWidget(content)
        self._operator_changed(self.operator.text())
        self._install_shortcuts()
        self.navigate("dashboard")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.toast_manager.reposition()

    def operator_name(self) -> str:
        operator = self.operator.text().strip()
        if not operator:
            self.operator.setFocus()
            raise ValueError("Enter an operator name before recording inventory activity.")
        return operator

    def _operator_changed(self, text: str) -> None:
        self.operator.setProperty("invalid", not bool(text.strip()))
        self.operator.style().unpolish(self.operator)
        self.operator.style().polish(self.operator)
        self.status.setText(f"Operator: {text.strip() or 'not set'}  |  Local mode  |  SQLite")

    def _save_operator(self) -> None:
        STORE.set_setting("last_operator", self.operator.text().strip())

    def toast(self, message: str, level: str = "info") -> None:
        self.toast_manager.show(message, level)

    def _install_shortcuts(self) -> None:
        self.shortcuts: list[QShortcut] = []
        search_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        search_shortcut.activated.connect(self._focus_global_search)
        self.shortcuts.append(search_shortcut)
        for index, key in enumerate(self.views, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda k=key: self.navigate(k))
            self.shortcuts.append(shortcut)

    def _focus_global_search(self) -> None:
        self.global_search.setFocus(Qt.ShortcutFocusReason)
        self.global_search.selectAll()

    def _submit_global_search(self) -> None:
        query = self.global_search.text().strip()
        self.navigate("parts")
        self.views["parts"].set_search(query)

    def open_part(self, part_number: str) -> None:
        self.navigate("parts")
        self.views["parts"].set_search(part_number, select_exact=True)

    def open_history(self, query: str = "") -> None:
        self.navigate("history")
        self.views["history"].set_search(query)

    def navigate(self, key: str) -> None:
        keys = list(self.views.keys())
        self.stack.setCurrentIndex(keys.index(key))
        for name, btn in self.nav_buttons.items():
            btn.setProperty("active", name == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.views[key].focus_primary()
