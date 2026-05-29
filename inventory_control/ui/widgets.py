from typing import List

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from inventory_control.store import STORE


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(10)
        self._shadow()
        if title:
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            self.layout.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("HelpText")
            sub.setWordWrap(True)
            self.layout.addWidget(sub)

    def _shadow(self) -> None:
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(16)
        effect.setOffset(0, 5)
        effect.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(effect)


class Toast(QFrame):
    COLORS = {"success": "#178553", "error": "#d14343", "warning": "#f6c343", "info": "#2f6fed"}

    def __init__(self, parent: QWidget, message: str, level: str = "info") -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        color = self.COLORS.get(level, self.COLORS["info"])
        self.setStyleSheet(
            "QFrame#Toast {"
            "background: #202326;"
            f"border-left: 6px solid {color};"
            "border-radius: 8px;"
            "}"
            "QLabel { background: transparent; color: white; font-weight: 750; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.setDuration(220)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.adjustSize()

    def fade_out(self) -> None:
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.setDuration(260)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()


class ToastManager:
    def __init__(self, parent: QWidget) -> None:
        self.parent = parent
        self.toasts: List[Toast] = []

    def show(self, message: str, level: str = "info") -> None:
        toast = Toast(self.parent, message, level)
        toast.show()
        self.toasts.append(toast)
        self.reposition()
        toast.anim.start()
        QTimer.singleShot(3300, toast.fade_out)
        toast.destroyed.connect(self.cleanup)

    def cleanup(self) -> None:
        self.toasts = [t for t in self.toasts if t is not None and not t.isHidden()]
        self.reposition()

    def reposition(self) -> None:
        margin = 20
        y = self.parent.height() - margin
        for toast in reversed(self.toasts[-4:]):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self.parent.width() - toast.width() - margin, y)
            y -= 10


class BaseView(QWidget):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 24)
        self.root.setSpacing(16)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        self.root.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("HelpText")
            sub.setWordWrap(True)
            self.root.addWidget(sub)


class PartCombo(QComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumHeight(44)
        completer = QCompleter(self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.setCompleter(completer)
        self.refresh()

    def refresh(self) -> None:
        current = self.currentText()
        self.clear()
        for part in STORE.parts.values():
            self.addItem(f"{part.part_number} - {part.description}", part.part_number)
        self.setCurrentText(current)

    def part_number(self) -> str:
        data = self.currentData()
        text = self.currentText().strip()
        if data:
            return str(data)
        if " - " in text:
            return text.split(" - ", 1)[0].strip().upper()
        return text.upper()


def add_field(layout: QVBoxLayout, label: str, widget: QWidget, required: bool = False, hint: str = "") -> None:
    label_row = QHBoxLayout()
    field_label = QLabel(label)
    field_label.setObjectName("FieldLabel")
    label_row.addWidget(field_label)
    if required:
        required_label = QLabel("Required")
        required_label.setObjectName("RequiredMark")
        label_row.addWidget(required_label)
    label_row.addStretch()
    layout.addLayout(label_row)
    widget.setMinimumHeight(44)
    widget.setAccessibleName(label)
    layout.addWidget(widget)
    if hint:
        hint_label = QLabel(hint)
        hint_label.setObjectName("HelpText")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
