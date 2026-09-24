"""Regression tests for inventory UI safety and responsive behavior."""

from PySide6.QtWidgets import QScrollArea, QTabWidget

import inventory_control.ui.main_window as main_window_module
import inventory_control.ui.views as views_module
import inventory_control.ui.widgets as widgets_module
from inventory_control.ui.main_window import MainWindow
from inventory_control.ui.views import (
    BOMView,
    DashboardView,
    HistoryView,
    MoveAdjustView,
    PartsView,
    ReceiveView,
    ShipView,
)
from inventory_control.ui.widgets import BaseView, PartCombo


def test_part_combo_starts_visibly_and_logically_unselected(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)

    combo = PartCombo()
    qtbot.addWidget(combo)

    assert combo.currentText() == ""
    assert combo.part_number() == ""
    assert combo.has_valid_part() is False


def test_part_combo_never_returns_stale_item_for_unmatched_text(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    combo = PartCombo()
    qtbot.addWidget(combo)

    combo.setCurrentIndex(combo.findData("ABC-1"))
    assert combo.part_number() == "ABC-1"

    combo.setEditText("NOT-A-PART")

    assert combo.part_number() == ""
    assert combo.has_valid_part() is False


def test_part_combo_hides_inactive_parts(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ACTIVE-1", "Active")
    blank_store.add_part("OLD-1", "Inactive")
    blank_store.set_part_active("OLD-1", False)
    monkeypatch.setattr(widgets_module, "STORE", blank_store)

    combo = PartCombo()
    qtbot.addWidget(combo)

    assert combo.findData("ACTIVE-1") >= 0
    assert combo.findData("OLD-1") == -1


def test_views_are_scrollable_at_laptop_heights(qtbot):
    view = BaseView("Test", "Scrollable content")
    qtbot.addWidget(view)

    assert isinstance(view, QScrollArea)
    assert view.widgetResizable() is True


def test_bom_shipping_auto_allocates_across_multiple_lots(qtbot, blank_store, monkeypatch):
    blank_store.add_part("KIT-1", "Kit")
    blank_store.add_part("COMP-1", "Component")
    blank_store.add_bom_component("KIT-1", "COMP-1", 5)
    blank_store.receive("COMP-1", 2, "Stock", "LOT-A", "setup")
    blank_store.receive("COMP-1", 3, "Stock", "LOT-B", "setup")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)

    view = ShipView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)
    view.part.setCurrentIndex(view.part.findData("KIT-1"))
    view.qty.setText("1")
    view.recipient.setText("Acme")
    view.update_preview()

    assert view.component_lot_table.rowCount() == 2
    assert {view.component_lot_table.item(row, 2).text() for row in range(2)} == {"LOT-A", "LOT-B"}
    assert sum(int(view.component_lot_table.item(row, 3).text()) for row in range(2)) == 5
    assert view.ship_btn.isEnabled() is True


def test_receive_uses_selected_parts_default_location(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget", location="Receiving")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = ReceiveView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)

    view.part.setCurrentIndex(view.part.findData("ABC-1"))

    assert view.location.currentText() == "Receiving"


def test_move_and_adjust_are_separate_task_tabs(qtbot, blank_store, monkeypatch):
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = MoveAdjustView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)

    assert isinstance(view.tabs, QTabWidget)
    assert [view.tabs.tabText(index) for index in range(view.tabs.count())] == ["Move Stock", "Adjust Count"]


def test_history_filters_across_operator_and_type(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget")
    blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "alice")
    blank_store.ship("ABC-1", 1, "Stock", "Acme", "bob", "LOT-1")
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = HistoryView()
    qtbot.addWidget(view)

    view.set_search("alice")
    assert view.table.rowCount() == 1
    assert view.table.item(0, 7).text() == "alice"

    view.search.clear()
    view.type_filter.setCurrentIndex(view.type_filter.findData("SHIP"))
    assert view.table.rowCount() == 1
    assert view.table.item(0, 1).text() == "SHIP"


def test_dashboard_items_open_their_related_record(qtbot, blank_store, monkeypatch):
    blank_store.add_part("LOW-1", "Low stock", minimum_quantity=2)
    blank_store.receive("LOW-1", 1, "Stock", "LOT-1", "alice")
    monkeypatch.setattr(views_module, "STORE", blank_store)
    opened_parts = []
    opened_history = []
    view = DashboardView(lambda *_: None, opened_parts.append, opened_history.append)
    qtbot.addWidget(view)

    view.low_list.itemActivated.emit(view.low_list.item(0))
    view.recent_list.itemActivated.emit(view.recent_list.item(0))

    assert opened_parts == ["LOW-1"]
    assert opened_history == ["LOW-1"]


def test_global_search_navigates_to_filtered_parts(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    monkeypatch.setattr(main_window_module, "STORE", blank_store)
    window = MainWindow()
    qtbot.addWidget(window)

    window.global_search.setText("ABC-1")
    window._submit_global_search()

    assert window.stack.currentWidget() is window.views["parts"]
    assert window.views["parts"].search.text() == "ABC-1"
    assert window.views["parts"].table.rowCount() == 1


def test_bom_row_selection_enters_explicit_update_mode(qtbot, blank_store, monkeypatch):
    blank_store.add_part("KIT-1", "Kit")
    blank_store.add_part("COMP-1", "Component")
    blank_store.add_bom_component("KIT-1", "COMP-1", 2)
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = BOMView(lambda *_: None)
    qtbot.addWidget(view)
    view.parent_part.setCurrentIndex(view.parent_part.findData("KIT-1"))
    view.refresh_direct_components()

    view.component_table.selectRow(0)

    assert view.editing_component == "COMP-1"
    assert view.quantity_per.text() == "2"
    assert view.component_save_btn.text() == "Update Component"
    assert view.component_save_btn.isEnabled() is True


def test_part_create_action_requires_required_fields(qtbot, blank_store, monkeypatch):
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = PartsView(lambda *_: None)
    qtbot.addWidget(view)

    assert view.add_btn.isEnabled() is False
    view.part_number.setText("ABC-1")
    assert view.add_btn.isEnabled() is False
    view.description.setText("Widget")
    assert view.add_btn.isEnabled() is True


def test_standard_shipping_hides_bom_allocation_table(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget")
    blank_store.receive("ABC-1", 2, "Stock", "LOT-1", "setup")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = ShipView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)

    view.part.setCurrentIndex(view.part.findData("ABC-1"))
    view.qty.setText("1")

    assert view.component_lot_table.isHidden() is True
