"""Regression tests for inventory UI safety and responsive behavior."""

from PySide6.QtWidgets import QScrollArea

import inventory_control.ui.views as views_module
import inventory_control.ui.widgets as widgets_module
from inventory_control.ui.views import ShipView
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

