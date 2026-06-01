"""
UI tests for toast notification lifecycle behavior.

These tests protect the small but important feedback loop operators depend on:
success and error messages must appear, stack predictably, and disappear without
leaving stale Qt objects in ToastManager.
"""

from PySide6.QtWidgets import QLabel, QWidget

from inventory_control.ui.widgets import ToastManager


def make_manager(qtbot, *, display_ms: int = 20, fade_in_ms: int = 1, fade_out_ms: int = 10) -> ToastManager:
    parent = QWidget()
    parent.resize(640, 480)
    qtbot.addWidget(parent)
    parent.show()
    return ToastManager(parent, display_ms=display_ms, fade_in_ms=fade_in_ms, fade_out_ms=fade_out_ms)


def toast_messages(manager: ToastManager) -> list[str]:
    messages = []
    for toast in manager.toasts:
        labels = toast.findChildren(QLabel)
        messages.extend(label.text() for label in labels)
    return messages


def test_creating_one_toast_tracks_it(qtbot):
    manager = make_manager(qtbot)

    manager.show("Saved.", "success")

    assert len(manager.toasts) == 1
    assert toast_messages(manager) == ["Saved."]


def test_one_toast_disappears_after_timeout(qtbot):
    manager = make_manager(qtbot)

    manager.show("Saved.", "success")

    qtbot.waitUntil(lambda: len(manager.toasts) == 0, timeout=500)

    assert manager.toasts == []


def test_sequential_toasts_all_disappear(qtbot):
    manager = make_manager(qtbot)

    manager.show("First.", "success")
    qtbot.wait(5)
    manager.show("Second.", "error")

    assert len(manager.toasts) == 2
    assert toast_messages(manager) == ["First.", "Second."]
    qtbot.waitUntil(lambda: len(manager.toasts) == 0, timeout=700)

    assert manager.toasts == []


def test_rapid_toasts_are_capped_to_latest_four_and_clean_up(qtbot):
    manager = make_manager(qtbot, display_ms=30)

    for index in range(6):
        manager.show(f"Toast {index}", "info")

    assert len(manager.toasts) == 4
    assert toast_messages(manager) == ["Toast 2", "Toast 3", "Toast 4", "Toast 5"]
    qtbot.waitUntil(lambda: len(manager.toasts) == 0, timeout=700)

    assert manager.toasts == []


def test_reposition_after_toast_expires_does_not_raise(qtbot):
    manager = make_manager(qtbot)

    manager.show("Temporary.", "info")
    qtbot.waitUntil(lambda: len(manager.toasts) == 0, timeout=500)

    manager.reposition()

    assert manager.toasts == []


def test_later_toast_still_works_after_earlier_toast_deleted(qtbot):
    manager = make_manager(qtbot)

    manager.show("Earlier.", "warning")
    qtbot.waitUntil(lambda: len(manager.toasts) == 0, timeout=500)
    manager.show("Later.", "success")

    assert len(manager.toasts) == 1
    assert toast_messages(manager) == ["Later."]
    qtbot.waitUntil(lambda: len(manager.toasts) == 0, timeout=500)

    assert manager.toasts == []
