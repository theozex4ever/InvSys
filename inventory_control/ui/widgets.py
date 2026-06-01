from typing import Callable, List

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

    def __init__(self, parent: QWidget, message: str, level: str = "info", fade_in_ms: int = 220, fade_out_ms: int = 260) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._fading_out = False
        self._fade_out_ms = fade_out_ms
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
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
        self.anim = QPropertyAnimation(self.effect, b"opacity")
        self.anim.setDuration(fade_in_ms)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.adjustSize()

    def start_auto_dismiss(self, display_ms: int, on_timeout: Callable[[], None]) -> None:
        self.dismiss_timer.timeout.connect(on_timeout)
        self.dismiss_timer.start(display_ms)

    def fade_out(self, on_finished: Callable[[], None]) -> None:
        if self._fading_out:
            return
        self._fading_out = True
        self.dismiss_timer.stop()
        self.anim = QPropertyAnimation(self.effect, b"opacity")
        self.anim.setDuration(self._fade_out_ms)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(on_finished)
        self.anim.start()


class ToastManager:
    def __init__(
        self,
        parent: QWidget,
        display_ms: int = 3300,
        fade_in_ms: int = 220,
        fade_out_ms: int = 260,
        max_visible: int = 4,
    ) -> None:
        self.parent = parent
        self.toasts: List[Toast] = []
        self.display_ms = display_ms
        self.fade_in_ms = fade_in_ms
        self.fade_out_ms = fade_out_ms
        self.max_visible = max_visible

    def show(self, message: str, level: str = "info") -> None:
        toast = Toast(self.parent, message, level, self.fade_in_ms, self.fade_out_ms)
        toast.show()
        self.toasts.append(toast)
        self._enforce_limit()
        self.reposition()
        toast.anim.start()
        toast.start_auto_dismiss(self.display_ms, lambda: self._fade_toast(toast))

    def _fade_toast(self, toast: Toast) -> None:
        if toast not in self.toasts:
            return
        toast.fade_out(lambda: self._finish_toast(toast))

    def _finish_toast(self, toast: Toast) -> None:
        self._remove_toast(toast)
        toast.anim.stop()
        toast.hide()
        toast.deleteLater()

    def _remove_toast(self, toast: Toast, reposition: bool = True) -> None:
        self.toasts = [existing for existing in self.toasts if existing is not toast]
        if reposition:
            self.reposition()

    def _enforce_limit(self) -> None:
        while len(self.toasts) > self.max_visible:
            toast = self.toasts.pop(0)
            toast.dismiss_timer.stop()
            toast.hide()
            toast.deleteLater()

    def reposition(self) -> None:
        margin = 20
        try:
            parent_width = self.parent.width()
            y = self.parent.height() - margin
        except RuntimeError:
            return
        for toast in reversed(self.toasts[-self.max_visible:]):
            try:
                toast.adjustSize()
                y -= toast.height()
                toast.move(parent_width - toast.width() - margin, y)
            except RuntimeError:
                continue
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
