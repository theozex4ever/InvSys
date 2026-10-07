"""Regression tests for inventory UI safety and responsive behavior."""

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QScrollArea, QTabWidget

import inventory_control.ui.main_window as main_window_module
import inventory_control.ui.views as views_module
import inventory_control.ui.widgets as widgets_module
from inventory_control.store import InventoryStore
from inventory_control.ui.main_window import MainWindow
from inventory_control.ui.bom_flowchart import BOMFlowchart, capacity_level
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


@pytest.mark.parametrize("notify_deactivation", [False, True])
def test_blocked_bom_draft_does_not_fail_receipt(qtbot, tmp_path, monkeypatch, notify_deactivation):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    store.add_part("P", "Component")
    store.add_part("KIT", "Kit")
    store.add_bom_component("KIT", "P", 1)
    store.receive("P", 2, "Stock", "L1", "setup")
    monkeypatch.setattr(widgets_module, "STORE", store)
    monkeypatch.setattr(views_module, "STORE", store)
    shipment = ShipView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(shipment)
    shipment.part.setCurrentIndex(shipment.part.findData("KIT"))
    shipment.qty.setText("1")
    shipment.recipient.setText("Acme")
    assert shipment.ship_btn.isEnabled()
    assert shipment.component_lot_table.rowCount() == 1

    toasts = []
    receipt = ReceiveView(lambda *args: toasts.append(args), lambda: "alice")
    qtbot.addWidget(receipt)
    receipt.part.setCurrentIndex(receipt.part.findData("KIT"))
    receipt.qty.setText("3")
    receipt.lot.setText("KIT-L1")
    receipt.reference.setText("delivery")
    store.set_part_active("P", False, notify=notify_deactivation)
    receipt.receive()

    assert store.stock_at("KIT", "Stock", "KIT-L1") == 3
    receipts = [tx for tx in store.transactions if tx.part_number == "KIT" and tx.tx_type == "RECEIVE"]
    assert len(receipts) == 1
    assert receipts[0].quantity_change == 3
    assert toasts[-1][1] == "success"
    assert "Received 3 of KIT" in receipt.result.text()
    assert receipt.qty.text() == receipt.lot.text() == receipt.reference.text() == ""
    assert not receipt.receive_btn.isEnabled()
    assert "Blocked:" in shipment.preview.text()
    assert "Part P is inactive" in shipment.preview.text()
    assert not shipment.ship_btn.isEnabled()
    assert shipment._bom_plan is None
    assert shipment.component_lot_table.rowCount() == 0
    assert shipment.qty.text() == "1"
    assert shipment.recipient.text() == "Acme"

    store.set_part_active("P", True)
    assert shipment.ship_btn.isEnabled()
    assert shipment.component_lot_table.rowCount() == 1
    store.engine.dispose()


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


def test_bom_shipping_requires_new_review_when_lots_change_during_confirmation(qtbot, blank_store, monkeypatch):
    blank_store.add_part("KIT-1", "Kit")
    blank_store.add_part("COMP-1", "Component")
    blank_store.add_bom_component("KIT-1", "COMP-1", 5)
    blank_store.receive("COMP-1", 5, "Stock", "LOT-B", "setup")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = ShipView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)
    view.part.setCurrentIndex(view.part.findData("KIT-1"))
    view.qty.setText("1")
    view.recipient.setText("Acme")

    def stock_changes_before_confirmation(*_args):
        blank_store.receive("COMP-1", 1, "Stock", "LOT-A", "setup")
        return QMessageBox.Yes

    monkeypatch.setattr(views_module.QMessageBox, "question", stock_changes_before_confirmation)
    view.ship()

    assert blank_store.shipments == []
    assert "Review the updated lots" in view.result.text()
    assert view.component_lot_table.item(0, 2).text() == "LOT-A"


def test_receive_uses_selected_parts_default_location(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget", location="Receiving")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = ReceiveView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)

    assert view.preview.isHidden()
    assert view.result.isHidden()
    view.part.setCurrentIndex(view.part.findData("ABC-1"))

    assert view.location.currentText() == "Receiving"
    assert not view.preview.isHidden()
    assert "Current at Receiving" in view.preview.text()
    assert view.result.isHidden()


def test_move_and_adjust_are_separate_task_tabs(qtbot, blank_store, monkeypatch):
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = MoveAdjustView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)

    assert isinstance(view.tabs, QTabWidget)
    assert [view.tabs.tabText(index) for index in range(view.tabs.count())] == ["Move Stock", "Adjust Count"]


def test_adjust_can_correct_a_fully_shipped_lot(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget")
    blank_store.receive("ABC-1", 5, "Stock", "LOT-1", "setup")
    blank_store.ship("ABC-1", 5, "Stock", "Acme", "alice", "LOT-1")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = MoveAdjustView(lambda *_: None, lambda: "alice")
    qtbot.addWidget(view)
    view.tabs.setCurrentIndex(1)
    view.adjust_part.setCurrentIndex(view.adjust_part.findData("ABC-1"))
    view.move_part.setCurrentIndex(view.move_part.findData("ABC-1"))
    view.move_qty.setText("1")

    assert blank_store.stock_at("ABC-1", "Stock", "LOT-1") == 0
    assert view.adjust_lot.currentText() == "LOT-1"
    assert view.move_lot.count() == 0
    assert view.move_btn.isEnabled() is False

    view.adjust_count.setText("2")
    assert view.adjust_btn.isEnabled() is False
    view.reason.setText("   ")
    assert view.adjust_btn.isEnabled() is False
    view.reason.setText("Found two units")
    assert view.adjust_btn.isEnabled() is True
    view.adjust_count.clear()
    assert view.adjust_btn.isEnabled() is False
    view.adjust_count.setText("2")
    view.adjust_lot.setCurrentIndex(-1)
    assert view.adjust_btn.isEnabled() is False
    view.adjust_lot.setCurrentIndex(view.adjust_lot.findText("LOT-1"))
    assert view.adjust_btn.isEnabled() is True
    assert "Adjustment: +2" in view.adjust_preview.text()

    transaction_count = len(blank_store.transactions)
    view.adjust_btn.click()

    assert blank_store.stock_at("ABC-1", "Stock", "LOT-1") == 2
    assert len(blank_store.transactions) == transaction_count + 1
    corrections = [tx for tx in blank_store.transactions if tx.tx_type == "COUNT_CORRECTION"]
    assert len(corrections) == 1
    correction = corrections[0]
    assert correction.quantity_change == 2
    assert correction.part_number == "ABC-1"
    assert correction.lot_number == "LOT-1"
    assert correction.reference == "Found two units"
    assert correction.operator == "alice"
    assert view.move_lot.currentText() == "LOT-1"


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

    assert window.stack.currentWidget() is window.sections["catalog"]
    assert window.group_stacks["catalog"].currentWidget() is window.views["parts"]
    assert window.views["parts"].search.text() == "ABC-1"
    assert window.views["parts"].table.rowCount() == 1


def test_sidebar_groups_related_views_without_losing_routes(qtbot, blank_store, monkeypatch):
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    monkeypatch.setattr(main_window_module, "STORE", blank_store)
    window = MainWindow()
    qtbot.addWidget(window)

    assert list(window.nav_buttons) == ["dashboard", "catalog", "stock", "history", "settings"]
    assert [window.group_bars["catalog"].tabText(i) for i in range(2)] == ["Parts", "BOM"]
    assert [window.group_bars["stock"].tabText(i) for i in range(4)] == [
        "Receive", "Ship", "Move", "Adjust"
    ]

    for key, section in [("bom", "catalog"), ("ship", "stock"), ("history", "history")]:
        window.navigate(key)
        assert window.stack.currentWidget() is window.sections[section]
        assert window.nav_buttons[section].property("active") is True

    window.navigate("adjust")
    assert window.group_stacks["stock"].currentWidget() is window.views["move"]
    assert window.views["move"].tabs.currentIndex() == 1
    assert window.views["move"].title_label.text() == "Adjust Count"
    assert window.views["move"].tabs.tabBar().isHidden()
    window.group_bars["stock"].setCurrentIndex(2)
    assert window.views["move"].tabs.currentIndex() == 0
    assert window.views["move"].title_label.text() == "Move Stock"
    window.navigate("catalog")
    assert window.group_stacks["catalog"].currentWidget() is window.views["bom"]


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


def test_bom_flowchart_uses_final_build_alert_thresholds(qtbot, blank_store, monkeypatch):
    blank_store.add_part("KIT", "Finished kit")
    blank_store.add_part("SCREW", "Screw")
    blank_store.add_bom_component("KIT", "SCREW", 2)
    blank_store.receive("SCREW", 200, "Stock", "LOT-1", "setup")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = BOMView(lambda *_: None)
    qtbot.addWidget(view)
    view.visual_part.setCurrentIndex(view.visual_part.findData("KIT"))

    assert isinstance(view.flowchart, BOMFlowchart)
    assert view.flowchart._node_count == 2
    assert view.capacity.property("level") == "critical"
    assert "100 final products" in view.capacity.text()

    blank_store.receive("SCREW", 800, "Stock", "LOT-2", "setup")
    assert view.capacity.property("level") == "low"
    assert "500 final products" in view.capacity.text()

    blank_store.receive("SCREW", 2, "Stock", "LOT-3", "setup")
    assert view.capacity.property("level") == "ready"
    assert "501 final products" in view.capacity.text()


def test_capacity_level_boundaries():
    assert capacity_level(0) == "critical"
    assert capacity_level(100) == "critical"
    assert capacity_level(101) == "low"
    assert capacity_level(500) == "low"
    assert capacity_level(501) == "ready"


def test_part_create_action_requires_required_fields(qtbot, blank_store, monkeypatch):
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = PartsView(lambda *_: None)
    qtbot.addWidget(view)

    assert view.add_btn.isEnabled() is False
    view.part_number.setText("ABC-1")
    assert view.add_btn.isEnabled() is False
    view.description.setText("Widget")
    assert view.add_btn.isEnabled() is True


def test_required_highlight_clears_and_returns_with_field_value(qtbot, blank_store, monkeypatch):
    monkeypatch.setattr(views_module, "STORE", blank_store)
    view = PartsView(lambda *_: None)
    qtbot.addWidget(view)
    label = next(
        item for item in view.findChildren(QLabel)
        if item.objectName() == "FieldLabel" and item.text() == "Part number"
    )

    assert view.part_number.property("missing") is True
    assert label.property("missing") is True

    view.part_number.setText("ABC-1")
    assert view.part_number.property("missing") is False
    assert label.property("missing") is False

    view.part_number.setText("   ")
    assert view.part_number.property("missing") is True
    assert label.property("missing") is True


def test_required_part_selector_clears_highlight_only_for_valid_part(qtbot, blank_store, monkeypatch):
    blank_store.add_part("ABC-1", "Widget")
    monkeypatch.setattr(widgets_module, "STORE", blank_store)
    combo = PartCombo()
    qtbot.addWidget(combo)
    label = QLabel("Part")
    widgets_module.bind_required_field(combo, label)

    assert combo.property("missing") is True
    combo.setEditText("NOT-A-PART")
    assert combo.property("missing") is True
    combo.setCurrentIndex(combo.findData("ABC-1"))
    assert combo.property("missing") is False
    assert label.property("missing") is False
    combo.refresh()
    assert combo.property("missing") is False
    combo.setCurrentIndex(-1)
    assert combo.property("missing") is True


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
