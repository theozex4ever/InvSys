from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
)

from inventory_control.backup import backup_database
from inventory_control.config import BACKUP_DIR, DB_PATH, EXPORT_DIR
from inventory_control.import_export import ImportExportService
from inventory_control.store import STORE
from inventory_control.models import LotAllocation
from inventory_control.ui.widgets import BaseView, Card, PartCombo, add_field, set_feedback


class DashboardView(BaseView):
    def __init__(self, navigate: Callable[[str], None]) -> None:
        super().__init__("Dashboard", "Fast actions first. Important warnings visible. No hunting.")
        grid = QGridLayout()
        grid.setSpacing(16)
        self.root.addLayout(grid)

        self.total_parts = QLabel()
        self.total_parts.setObjectName("Metric")
        self.total_stock = QLabel()
        self.total_stock.setObjectName("Metric")
        self.low_count = QLabel()
        self.low_count.setObjectName("Metric")

        for i, (title, metric) in enumerate(
            [("Parts", self.total_parts), ("Units On Hand", self.total_stock), ("Low Stock", self.low_count)]
        ):
            card = Card(title)
            card.layout.addWidget(metric)
            grid.addWidget(card, 0, i)

        actions = Card("Quick Actions", "One clear path into each common job.")
        action_row = QHBoxLayout()
        for text, screen, obj in [
            ("Receive Stock", "receive", "SuccessButton"),
            ("Ship Stock", "ship", "DangerButton"),
            ("Find Part", "parts", "SecondaryButton"),
        ]:
            btn = QPushButton(text)
            btn.setMinimumHeight(50)
            btn.setObjectName(obj)
            btn.clicked.connect(lambda _, s=screen: navigate(s))
            action_row.addWidget(btn)
        actions.layout.addLayout(action_row)
        grid.addWidget(actions, 1, 0, 1, 3)

        self.low_list = QListWidget()
        self.recent_list = QListWidget()
        low_card = Card("Low Stock", "Items at or below minimum quantity.")
        low_card.layout.addWidget(self.low_list)
        recent_card = Card("Recent Activity", "Latest inventory movements.")
        recent_card.layout.addWidget(self.recent_list)
        grid.addWidget(low_card, 2, 0, 1, 1)
        grid.addWidget(recent_card, 2, 1, 1, 2)
        self.root.addStretch()
        STORE.subscribe(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        active_parts = [part for part in STORE.parts.values() if part.active]
        self.total_parts.setText(str(len(active_parts)))
        self.total_stock.setText(str(sum(STORE.total_stock(part.part_number) for part in active_parts)))
        self.low_count.setText(str(len(STORE.low_stock())))
        self.low_list.clear()
        for part in STORE.low_stock():
            self.low_list.addItem(
                f"Low: {part.part_number}   {STORE.total_stock(part.part_number)} / min {part.minimum_quantity}"
            )
        if self.low_list.count() == 0:
            self.low_list.addItem("No low-stock items")
        self.recent_list.clear()
        for tx in STORE.transactions[:8]:
            self.recent_list.addItem(f"{tx.timestamp}  {tx.tx_type}  {tx.part_number}  {tx.quantity_change:+d}")


class PartsView(BaseView):
    def __init__(self, toast: Callable[[str, str], None]) -> None:
        super().__init__("Parts", "Create and find part records. Keep names consistent.")
        self.toast = toast
        row = QHBoxLayout()
        row.setSpacing(16)
        self.root.addLayout(row)

        form = Card("Add Part", "Required fields are marked before the input.")
        self.part_number = QLineEdit()
        self.part_number.setPlaceholderText("ABC-123")
        self.description = QLineEdit()
        self.description.setPlaceholderText("Bearing assembly")
        self.minimum = QLineEdit("0")
        self.minimum.setValidator(QIntValidator(0, 999999))
        self.location = QComboBox()
        self.location.addItems(STORE.locations)
        self.add_btn = QPushButton("Add Part")
        self.add_btn.setMinimumHeight(50)
        self.add_btn.clicked.connect(self.add_part)
        self.edit_btn = QPushButton("Save Selected Part")
        self.edit_btn.setObjectName("SecondaryButton")
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self.edit_part)
        self.new_btn = QPushButton("Clear / New Part")
        self.new_btn.setObjectName("SecondaryButton")
        self.new_btn.clicked.connect(self._clear_part_form)
        add_field(form.layout, "Part number", self.part_number, required=True)
        add_field(form.layout, "Description", self.description, required=True)
        add_field(form.layout, "Minimum quantity", self.minimum)
        add_field(form.layout, "Default location", self.location)
        form.layout.addWidget(self.add_btn)
        form.layout.addWidget(self.edit_btn)
        form.layout.addWidget(self.new_btn)
        row.addWidget(form, 1)

        list_card = Card("Part List", "Search by number or description.")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search parts")
        self.search.textChanged.connect(self.refresh)
        self.show_inactive = QCheckBox("Show inactive parts")
        self.show_inactive.toggled.connect(self.refresh)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Part", "Description", "Total", "Min", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self.select_part)
        self.toggle_active_btn = QPushButton("Deactivate Selected")
        self.toggle_active_btn.setObjectName("SecondaryButton")
        self.toggle_active_btn.setEnabled(False)
        self.toggle_active_btn.clicked.connect(self.toggle_selected_part)
        add_field(list_card.layout, "Search", self.search)
        list_card.layout.addWidget(self.show_inactive)
        list_card.layout.addWidget(self.table)
        list_card.layout.addWidget(self.toggle_active_btn)
        row.addWidget(list_card, 2)
        STORE.subscribe(self.refresh)
        self.refresh()

    def add_part(self) -> None:
        try:
            STORE.add_part(
                self.part_number.text(),
                self.description.text(),
                int(self.minimum.text() or 0),
                self.location.currentText(),
            )
            self.toast(f"Part added: {self.part_number.text().strip().upper()}", "success")
            self._clear_part_form()
        except ValueError as e:
            self.toast(str(e), "error")

    def edit_part(self) -> None:
        selected = self._selected_part_number()
        if not selected:
            self.toast("Select a part to edit.", "error")
            return
        try:
            existing = STORE.parts[selected]
            STORE.upsert_part(
                selected,
                self.description.text(),
                int(self.minimum.text() or 0),
                self.location.currentText(),
                existing.active,
            )
            self.toast(f"Part updated: {selected}", "success")
        except ValueError as e:
            self.toast(str(e), "error")

    def select_part(self) -> None:
        selected = self._selected_part_number()
        enabled = bool(selected)
        self.edit_btn.setEnabled(enabled)
        self.toggle_active_btn.setEnabled(enabled)
        self.add_btn.setEnabled(not enabled)
        if not selected:
            return
        part = STORE.parts[selected]
        self.part_number.setText(part.part_number)
        self.part_number.setEnabled(False)
        self.description.setText(part.description)
        self.minimum.setText(str(part.minimum_quantity))
        self.location.setCurrentText(part.location)
        self.toggle_active_btn.setText("Deactivate Selected" if part.active else "Reactivate Selected")

    def toggle_selected_part(self) -> None:
        selected = self._selected_part_number()
        if not selected:
            return
        part = STORE.parts[selected]
        if part.active and STORE.total_stock(selected) > 0:
            answer = QMessageBox.question(
                self,
                "Deactivate part with stock?",
                f"{selected} still has {STORE.total_stock(selected)} units on hand. Deactivate it anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        STORE.set_part_active(selected, not part.active)
        self.toast(f"{selected} {'reactivated' if not part.active else 'deactivated'}.", "success")
        self._clear_part_form()

    def _selected_part_number(self) -> str:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.text() if item is not None else ""

    def _clear_part_form(self) -> None:
        self.table.clearSelection()
        self.part_number.setEnabled(True)
        self.part_number.clear()
        self.description.clear()
        self.minimum.setText("0")
        self.edit_btn.setEnabled(False)
        self.toggle_active_btn.setEnabled(False)
        self.add_btn.setEnabled(True)

    def refresh(self) -> None:
        query = self.search.text().lower().strip() if hasattr(self, "search") else ""
        include_inactive = self.show_inactive.isChecked() if hasattr(self, "show_inactive") else False
        rows = [
            p for p in STORE.parts.values()
            if (p.active or include_inactive) and (query in p.part_number.lower() or query in p.description.lower())
        ]
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            values = [
                p.part_number,
                p.description,
                str(STORE.total_stock(p.part_number)),
                str(p.minimum_quantity),
                "Active" if p.active else "Inactive",
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.table.setItem(r, c, item)


class BOMView(BaseView):
    def __init__(self, toast: Callable[[str, str], None]) -> None:
        super().__init__("BOM", "Build nested part structures and verify component availability before shipping.")
        self.toast = toast
        row = QHBoxLayout()
        row.setSpacing(16)
        self.root.addLayout(row)

        builder = Card("BOM Builder", "Add direct components. Nested levels appear automatically in the visualizer.")
        self.parent_part = PartCombo()
        self.component_part = PartCombo()
        self.quantity_per = QLineEdit("1")
        self.quantity_per.setValidator(QIntValidator(1, 999999))
        add_btn = QPushButton("Add / Update Component")
        add_btn.setMinimumHeight(50)
        add_btn.clicked.connect(self.add_component)
        self.component_table = QTableWidget(0, 3)
        self.component_table.setHorizontalHeaderLabels(["Component", "Description", "Qty per"])
        self.component_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.component_table.verticalHeader().setVisible(False)
        self.component_table.setSelectionBehavior(QTableWidget.SelectRows)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.setObjectName("SecondaryButton")
        remove_btn.clicked.connect(self.remove_component)
        add_field(builder.layout, "Parent assembly / kit", self.parent_part, required=True)
        add_field(builder.layout, "Component part", self.component_part, required=True)
        add_field(builder.layout, "Quantity per parent", self.quantity_per, required=True)
        builder.layout.addWidget(add_btn)
        builder.layout.addWidget(self.component_table)
        builder.layout.addWidget(remove_btn)
        row.addWidget(builder, 1)

        visual = Card("BOM Trace", "Tree shows nesting. Requirements show the exact leaf parts consumed by shipping.")
        self.visual_part = PartCombo()
        self.build_qty = QLineEdit("1")
        self.build_qty.setValidator(QIntValidator(1, 999999))
        self.location = QComboBox()
        self.location.addItems(STORE.locations)
        self.location.setCurrentText("Stock")
        self.summary = QLabel()
        self.summary.setObjectName("HelpText")
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Part", "Required", "Stock", "Status"])
        self.requirements = QTableWidget(0, 5)
        self.requirements.setHorizontalHeaderLabels(["Component", "Description", "Required", "Available", "Shortage"])
        self.requirements.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.requirements.verticalHeader().setVisible(False)
        add_field(visual.layout, "Visualize part", self.visual_part, required=True)
        add_field(visual.layout, "Ship quantity", self.build_qty, required=True)
        add_field(visual.layout, "Consume from location", self.location, required=True)
        visual.layout.addWidget(self.summary)
        visual.layout.addWidget(self.tree)
        visual.layout.addWidget(self.requirements)
        row.addWidget(visual, 2)

        self.parent_part.currentTextChanged.connect(self.refresh_direct_components)
        self.visual_part.currentTextChanged.connect(self.update_visual)
        self.build_qty.textChanged.connect(self.update_visual)
        self.location.currentTextChanged.connect(self.update_visual)
        STORE.subscribe(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.parent_part.refresh()
        self.component_part.refresh()
        self.visual_part.refresh()
        self.refresh_direct_components()
        self.update_visual()

    def add_component(self) -> None:
        try:
            STORE.add_bom_component(
                self.parent_part.part_number(),
                self.component_part.part_number(),
                int(self.quantity_per.text() or 0),
            )
            self.toast("BOM component saved.", "success")
        except ValueError as e:
            self.toast(str(e), "error")

    def remove_component(self) -> None:
        row = self.component_table.currentRow()
        if row < 0:
            self.toast("Select a BOM component first.", "error")
            return
        component = self.component_table.item(row, 0).text()
        answer = QMessageBox.question(
            self,
            "Remove BOM component?",
            f"Remove {component} from {self.parent_part.part_number()}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            STORE.remove_bom_component(self.parent_part.part_number(), component)
            self.toast("BOM component removed.", "success")
        except ValueError as e:
            self.toast(str(e), "error")

    def refresh_direct_components(self) -> None:
        parent = self.parent_part.part_number()
        children = STORE.bom_children(parent) if parent in STORE.parts else []
        self.component_table.setRowCount(len(children))
        for r, child in enumerate(children):
            part = STORE.parts[child.component_part_number]
            values = [child.component_part_number, part.description, str(child.quantity_per)]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.component_table.setItem(r, c, item)

    def update_visual(self) -> None:
        part_number = self.visual_part.part_number()
        qty = int(self.build_qty.text() or 0)
        location = self.location.currentText()
        self.tree.clear()
        self.requirements.setRowCount(0)
        if part_number not in STORE.parts or qty <= 0:
            self.summary.setText("Choose a part and quantity.")
            return
        try:
            root = STORE.bom_tree(part_number, qty, location)
            root_item = self._tree_item(root)
            self.tree.addTopLevelItem(root_item)
            root_item.setExpanded(True)
            self.tree.expandAll()
            requirements = STORE.bom_requirements(part_number, qty, location)
        except ValueError as e:
            self.summary.setText(str(e))
            return

        if not requirements:
            self.summary.setText("This part has no BOM. Shipping deducts the part itself.")
            return

        self.requirements.setRowCount(len(requirements))
        total_shortage = 0
        for r, req in enumerate(requirements):
            total_shortage += req.shortage
            values = [
                req.part_number,
                req.description,
                str(req.quantity_required),
                str(req.stock_available),
                str(req.shortage),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.requirements.setItem(r, c, item)
        if total_shortage:
            self.summary.setText(f"Blocked: component shortage totals {total_shortage} units.")
        else:
            self.summary.setText("Ready: all required BOM components are available.")

    def _tree_item(self, node) -> QTreeWidgetItem:
        shortage = max(node.quantity_required - node.stock_available, 0) if not node.children else 0
        status = "Assembly" if node.children else ("OK" if shortage == 0 else f"Short {shortage}")
        item = QTreeWidgetItem(
            [
                f"{node.part_number} - {node.description}",
                str(node.quantity_required),
                str(node.stock_available),
                status,
            ]
        )
        for child in node.children:
            item.addChild(self._tree_item(child))
        return item


class ReceiveView(BaseView):
    def __init__(self, toast: Callable[[str, str], None], operator_getter: Callable[[], str]) -> None:
        super().__init__("Receive Stock", "Add inventory. Confirmation shows the new quantity.")
        self.toast = toast
        self.operator_getter = operator_getter
        card = Card("Receive", "Select part, quantity, and location. Then receive.")
        self.root.addWidget(card)
        self.part = PartCombo()
        self.qty = QLineEdit()
        self.qty.setValidator(QIntValidator(1, 999999))
        self.qty.setPlaceholderText("Quantity")
        self.location = QComboBox()
        self.location.addItems(STORE.locations)
        self.location.setCurrentText("Stock")
        self.lot = QLineEdit()
        self.lot.setPlaceholderText("Required lot number")
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("PO, project, or note")
        self.preview = QLabel("Choose a part and quantity.")
        self.preview.setObjectName("HelpText")
        self.result = QLabel("Complete the required fields to receive stock.")
        self.result.setObjectName("FeedbackLabel")
        self.receive_btn = QPushButton("Receive Stock")
        self.receive_btn.setObjectName("SuccessButton")
        self.receive_btn.setMinimumHeight(50)
        self.receive_btn.setEnabled(False)
        self.receive_btn.clicked.connect(self.receive)
        add_field(card.layout, "Part", self.part, required=True)
        add_field(card.layout, "Quantity", self.qty, required=True)
        add_field(card.layout, "Location", self.location, required=True)
        add_field(card.layout, "Lot number", self.lot, required=True)
        add_field(card.layout, "Reference", self.reference, hint="Optional.")
        card.layout.addWidget(self.preview)
        card.layout.addWidget(self.result)
        card.layout.addWidget(self.receive_btn)
        self.part.currentTextChanged.connect(self.update_preview)
        self.qty.textChanged.connect(self.update_preview)
        self.location.currentTextChanged.connect(self.update_preview)
        self.lot.textChanged.connect(self.update_preview)
        STORE.subscribe(self.refresh)

    def refresh(self) -> None:
        self.part.refresh()
        self.update_preview()

    def update_preview(self) -> None:
        pn = self.part.part_number()
        loc = self.location.currentText()
        stock = STORE.stock_at(pn, loc) if pn in STORE.parts else 0
        qty = int(self.qty.text() or 0)
        valid = bool(pn and qty > 0 and self.lot.text().strip())
        self.receive_btn.setEnabled(valid)
        if not pn:
            self.preview.setText("Select a valid part.")
        else:
            self.preview.setText(f"Current at {loc}: {stock}  →  after receive: {stock + qty}")

    def receive(self) -> None:
        try:
            pn = self.part.part_number()
            qty = int(self.qty.text() or 0)
            loc = self.location.currentText()
            lot = self.lot.text()
            STORE.receive(pn, qty, loc, lot, self.operator_getter(), self.reference.text())
            self.toast(f"Received {qty} {pn} lot {lot.strip().upper()}. New stock in {loc}: {STORE.stock_at(pn, loc)}.", "success")
            self.qty.clear()
            self.lot.clear()
            self.reference.clear()
            set_feedback(
                self.result,
                f"Received {qty} of {pn}, lot {lot.strip().upper()}. Current stock in {loc}: {STORE.stock_at(pn, loc)}.",
                "success",
            )
        except ValueError as e:
            set_feedback(self.result, str(e), "error")
            self.toast(str(e), "error")


class ShipView(BaseView):
    def __init__(self, toast: Callable[[str, str], None], operator_getter: Callable[[], str]) -> None:
        super().__init__("Ship Stock", "Deduct stock and create a simple shipment record.")
        self.toast = toast
        self.operator_getter = operator_getter
        card = Card("Ship", "Negative inventory is blocked before the shipment is created.")
        self.root.addWidget(card)
        self.part = PartCombo()
        self.qty = QLineEdit()
        self.qty.setValidator(QIntValidator(1, 999999))
        self.qty.setPlaceholderText("Quantity")
        self.location = QComboBox()
        self.location.addItems(STORE.locations)
        self.location.setCurrentText("Stock")
        self.lot = QComboBox()
        self.lot.setEditable(False)
        self.recipient = QLineEdit()
        self.recipient.setPlaceholderText("Project, customer, or recipient")
        self.carrier = QLineEdit()
        self.carrier.setPlaceholderText("UPS, FedEx, handoff")
        self.tracking = QLineEdit()
        self.tracking.setPlaceholderText("Tracking number")
        self.preview = QLabel("Choose a part and quantity.")
        self.preview.setObjectName("HelpText")
        self.component_lot_table = QTableWidget(0, 5)
        self.component_lot_table.setHorizontalHeaderLabels(["Component", "Required", "Auto lot", "Allocated", "Lot stock"])
        self.component_lot_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.component_lot_table.verticalHeader().setVisible(False)
        self.result = QLabel("Complete the required fields to create a shipment.")
        self.result.setObjectName("FeedbackLabel")
        self.ship_btn = QPushButton("Review & Ship")
        self.ship_btn.setMinimumHeight(50)
        self.ship_btn.setEnabled(False)
        self.ship_btn.clicked.connect(self.ship)
        add_field(card.layout, "Part", self.part, required=True)
        add_field(card.layout, "Quantity", self.qty, required=True)
        add_field(card.layout, "Location", self.location, required=True)
        add_field(card.layout, "Lot", self.lot, required=True, hint="For BOM shipments, select lots in the component table below.")
        add_field(card.layout, "Recipient / project", self.recipient, required=True)
        add_field(card.layout, "Carrier", self.carrier, hint="Optional.")
        add_field(card.layout, "Tracking number", self.tracking, hint="Optional.")
        card.layout.addWidget(self.preview)
        card.layout.addWidget(self.component_lot_table)
        card.layout.addWidget(self.result)
        card.layout.addWidget(self.ship_btn)
        self.part.currentTextChanged.connect(self.update_preview)
        self.qty.textChanged.connect(self.update_preview)
        self.location.currentTextChanged.connect(self.update_preview)
        self.lot.currentTextChanged.connect(self.update_preview)
        self.recipient.textChanged.connect(self.update_preview)
        STORE.subscribe(self.refresh)

    def refresh(self) -> None:
        self.part.refresh()
        self.update_preview()

    def update_preview(self) -> None:
        pn = self.part.part_number()
        loc = self.location.currentText()
        self._refresh_lot_combo()
        self.component_lot_table.setRowCount(0)
        stock = STORE.stock_at(pn, loc) if pn in STORE.parts else 0
        qty = int(self.qty.text() or 0)
        self.ship_btn.setEnabled(False)
        if not pn:
            self.preview.setText("Select a valid part.")
            return
        if pn in STORE.parts and qty > 0 and STORE.has_bom(pn):
            requirements = STORE.bom_requirements(pn, qty, loc)
            allocations_complete = self._refresh_component_lots(requirements, loc)
            shortages = [req for req in requirements if req.shortage > 0]
            if shortages or not allocations_complete:
                detail = "; ".join(f"{req.part_number} short {req.shortage}" for req in shortages[:3])
                self.preview.setText(f"Blocked: BOM component shortage. {detail}".rstrip())
            else:
                count = len(requirements)
                total = sum(req.quantity_required for req in requirements)
                self.preview.setText(f"Ready: auto-allocated {total} units across {count} component parts using lot order.")
                self.ship_btn.setEnabled(bool(self.recipient.text().strip()))
            return
        lot = self.lot.currentText()
        lot_stock = STORE.stock_at(pn, loc, lot) if pn in STORE.parts and lot else 0
        after = lot_stock - qty
        marker = "OK" if after >= 0 else "Blocked"
        self.preview.setText(f"{marker}: selected lot at {loc}: {lot_stock} / total {stock}  ->  after ship: {after}")
        self.ship_btn.setEnabled(bool(qty > 0 and lot and after >= 0 and self.recipient.text().strip()))

    def ship(self) -> None:
        try:
            pn = self.part.part_number()
            qty = int(self.qty.text() or 0)
            loc = self.location.currentText()
            operator = self.operator_getter()
            component_lots = self._selected_component_lots(loc) if pn in STORE.parts and STORE.has_bom(pn) else None
            if not self.ship_btn.isEnabled():
                raise ValueError("Complete the required fields and resolve stock shortages before shipping.")
            allocation_text = "BOM lots shown in the allocation table" if component_lots is not None else f"lot {self.lot.currentText()}"
            answer = QMessageBox.question(
                self,
                "Confirm shipment",
                f"Ship {qty} of {pn} from {loc} using {allocation_text} to {self.recipient.text().strip()}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            sn = STORE.ship(
                pn,
                qty,
                loc,
                self.recipient.text(),
                operator,
                self.lot.currentText() if component_lots is None else None,
                component_lots,
                self.carrier.text(),
                self.tracking.text(),
            )
            suffix = " BOM components deducted." if STORE.shipments and STORE.shipments[0].consumed_components else ""
            self.toast(f"Shipped {qty} of {pn}. Shipment: {sn}.{suffix}", "success")
            self.qty.clear()
            self.recipient.clear()
            self.carrier.clear()
            self.tracking.clear()
            set_feedback(self.result, f"Shipment {sn} created: {qty} of {pn} shipped from {loc}.", "success")
        except ValueError as e:
            set_feedback(self.result, str(e), "error")
            self.toast(str(e), "error")

    def _refresh_lot_combo(self) -> None:
        current = self.lot.currentText()
        self.lot.blockSignals(True)
        self.lot.clear()
        pn = self.part.part_number()
        loc = self.location.currentText()
        if pn in STORE.parts:
            for lot in STORE.lots_for_part(pn, loc, positive_only=True):
                self.lot.addItem(lot.lot_number)
        self.lot.setCurrentText(current)
        self.lot.blockSignals(False)

    def _refresh_component_lots(self, requirements, location: str) -> bool:
        rows: list[tuple[str, int, str, int, int]] = []
        complete = True
        for req in requirements:
            remaining = req.quantity_required
            lots = STORE.lots_for_part(req.part_number, location, positive_only=True)
            for lot in lots:
                available = STORE.stock_at(req.part_number, location, lot.lot_number)
                allocated = min(remaining, available)
                if allocated > 0:
                    rows.append((req.part_number, req.quantity_required, lot.lot_number, allocated, available))
                    remaining -= allocated
                if remaining == 0:
                    break
            if remaining > 0:
                complete = False
                if not lots:
                    rows.append((req.part_number, req.quantity_required, "No stock lot", 0, 0))
        self.component_lot_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.component_lot_table.setItem(row, col, item)
        return complete

    def _selected_component_lots(self, location: str) -> list[LotAllocation]:
        allocations: list[LotAllocation] = []
        for row in range(self.component_lot_table.rowCount()):
            part_item = self.component_lot_table.item(row, 0)
            qty_item = self.component_lot_table.item(row, 1)
            lot_item = self.component_lot_table.item(row, 2)
            allocation_item = self.component_lot_table.item(row, 3)
            if part_item is None or qty_item is None or lot_item is None or allocation_item is None:
                continue
            allocations.append(
                LotAllocation(
                    part_item.text(),
                    lot_item.text(),
                    location,
                    int(allocation_item.text() or 0),
                )
            )
        return allocations


class MoveAdjustView(BaseView):
    def __init__(self, toast: Callable[[str, str], None], operator_getter: Callable[[], str]) -> None:
        super().__init__("Move / Adjust", "Move stock between locations or correct a physical count.")
        self.toast = toast
        self.operator_getter = operator_getter
        row = QHBoxLayout()
        row.setSpacing(16)
        self.root.addLayout(row)

        move = Card("Move Stock", "Source decreases. Destination increases.")
        self.move_part = PartCombo()
        self.move_qty = QLineEdit()
        self.move_qty.setValidator(QIntValidator(1, 999999))
        self.move_qty.setPlaceholderText("Quantity")
        self.move_from = QComboBox()
        self.move_from.addItems(STORE.locations)
        self.move_from.setCurrentText("Stock")
        self.move_lot = QComboBox()
        self.move_to = QComboBox()
        self.move_to.addItems(STORE.locations)
        self.move_to.setCurrentText("Shipping Bench")
        self.move_preview = QLabel("Select a part, lot, and quantity.")
        self.move_preview.setObjectName("FeedbackLabel")
        self.move_btn = QPushButton("Move Stock")
        self.move_btn.setMinimumHeight(50)
        self.move_btn.setEnabled(False)
        self.move_btn.clicked.connect(self.move_stock)
        add_field(move.layout, "Part", self.move_part, required=True)
        add_field(move.layout, "Quantity", self.move_qty, required=True)
        add_field(move.layout, "From", self.move_from, required=True)
        add_field(move.layout, "Lot", self.move_lot, required=True)
        add_field(move.layout, "To", self.move_to, required=True)
        move.layout.addWidget(self.move_preview)
        move.layout.addWidget(self.move_btn)
        row.addWidget(move)

        adjust = Card("Adjust Count", "Requires a reason. Keeps the audit trail.")
        self.adjust_part = PartCombo()
        self.adjust_count = QLineEdit()
        self.adjust_count.setValidator(QIntValidator(0, 999999))
        self.adjust_count.setPlaceholderText("New counted quantity")
        self.adjust_location = QComboBox()
        self.adjust_location.addItems(STORE.locations)
        self.adjust_location.setCurrentText("Stock")
        self.adjust_lot = QComboBox()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Why the count changed")
        self.adjust_preview = QLabel("Select a part and enter the physical count.")
        self.adjust_preview.setObjectName("FeedbackLabel")
        self.adjust_btn = QPushButton("Review Count Correction")
        self.adjust_btn.setObjectName("SecondaryButton")
        self.adjust_btn.setMinimumHeight(50)
        self.adjust_btn.setEnabled(False)
        self.adjust_btn.clicked.connect(self.adjust_stock)
        add_field(adjust.layout, "Part", self.adjust_part, required=True)
        add_field(adjust.layout, "New counted quantity", self.adjust_count, required=True)
        add_field(adjust.layout, "Location", self.adjust_location, required=True)
        add_field(adjust.layout, "Lot", self.adjust_lot, required=True)
        add_field(adjust.layout, "Reason", self.reason, required=True)
        adjust.layout.addWidget(self.adjust_preview)
        adjust.layout.addWidget(self.adjust_btn)
        row.addWidget(adjust)
        self.move_part.currentTextChanged.connect(self.refresh_lots)
        self.move_from.currentTextChanged.connect(self.refresh_lots)
        self.adjust_part.currentTextChanged.connect(self.refresh_lots)
        self.adjust_location.currentTextChanged.connect(self.refresh_lots)
        self.move_qty.textChanged.connect(self.update_previews)
        self.move_lot.currentTextChanged.connect(self.update_previews)
        self.move_to.currentTextChanged.connect(self.update_previews)
        self.adjust_count.textChanged.connect(self.update_previews)
        self.adjust_lot.currentTextChanged.connect(self.update_previews)
        self.reason.textChanged.connect(self.update_previews)
        STORE.subscribe(self.refresh)

    def refresh(self) -> None:
        self.move_part.refresh()
        self.adjust_part.refresh()
        self.refresh_lots()

    def refresh_lots(self) -> None:
        self._fill_lots(self.move_lot, self.move_part.part_number(), self.move_from.currentText())
        self._fill_lots(self.adjust_lot, self.adjust_part.part_number(), self.adjust_location.currentText())
        self.update_previews()

    def update_previews(self) -> None:
        move_part = self.move_part.part_number()
        move_qty = int(self.move_qty.text() or 0)
        move_lot = self.move_lot.currentText()
        source = self.move_from.currentText()
        target = self.move_to.currentText()
        available = STORE.stock_at(move_part, source, move_lot) if move_part and move_lot else 0
        move_valid = bool(move_part and move_lot and move_qty > 0 and source != target and move_qty <= available)
        self.move_btn.setEnabled(move_valid)
        if move_part and move_lot:
            set_feedback(
                self.move_preview,
                f"{source}: {available} → {available - move_qty}; {target} receives {move_qty}.",
                "info" if move_valid else "warning",
            )

        adjust_part = self.adjust_part.part_number()
        adjust_lot = self.adjust_lot.currentText()
        count_text = self.adjust_count.text()
        current = STORE.stock_at(adjust_part, self.adjust_location.currentText(), adjust_lot) if adjust_part and adjust_lot else 0
        new_count = int(count_text or 0)
        adjust_valid = bool(adjust_part and adjust_lot and count_text and self.reason.text().strip())
        self.adjust_btn.setEnabled(adjust_valid)
        if adjust_part and adjust_lot and count_text:
            diff = new_count - current
            set_feedback(
                self.adjust_preview,
                f"Current: {current}. New count: {new_count}. Adjustment: {diff:+d}.",
                "warning" if diff else "info",
            )

    def _fill_lots(self, combo: QComboBox, part_number: str, location: str) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        if part_number in STORE.parts:
            for lot in STORE.lots_for_part(part_number, location, positive_only=True):
                combo.addItem(lot.lot_number)
        combo.setCurrentText(current)
        combo.blockSignals(False)

    def move_stock(self) -> None:
        try:
            STORE.move(
                self.move_part.part_number(),
                int(self.move_qty.text() or 0),
                self.move_from.currentText(),
                self.move_to.currentText(),
                self.move_lot.currentText(),
                self.operator_getter(),
            )
            self.toast("Stock moved.", "success")
            self.move_qty.clear()
            set_feedback(self.move_preview, "Stock moved successfully. The paired move transactions are in History.", "success")
        except ValueError as e:
            set_feedback(self.move_preview, str(e), "error")
            self.toast(str(e), "error")

    def adjust_stock(self) -> None:
        try:
            part = self.adjust_part.part_number()
            location = self.adjust_location.currentText()
            lot = self.adjust_lot.currentText()
            new_count = int(self.adjust_count.text() or 0)
            current = STORE.stock_at(part, location, lot)
            diff = new_count - current
            operator = self.operator_getter()
            if abs(diff) >= max(10, max(current // 2, 1)):
                answer = QMessageBox.question(
                    self,
                    "Confirm large count correction",
                    f"Change {part} lot {lot} at {location} from {current} to {new_count} ({diff:+d})?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return
            diff = STORE.adjust(
                part,
                location,
                lot,
                new_count,
                operator,
                self.reason.text(),
            )
            self.toast(f"Count corrected. Difference: {diff:+d}.", "success")
            self.adjust_count.clear()
            self.reason.clear()
            set_feedback(self.adjust_preview, f"Count corrected by {diff:+d}. The correction is in History.", "success")
        except ValueError as e:
            set_feedback(self.adjust_preview, str(e), "error")
            self.toast(str(e), "error")


class HistoryView(BaseView):
    def __init__(self) -> None:
        super().__init__("History", "Trace inventory activity. No hidden changes.")
        card = Card("Transactions")
        self.root.addWidget(card)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Part", "Lot", "Qty", "From", "To", "Operator", "Reference"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        card.layout.addWidget(self.table)
        STORE.subscribe(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(len(STORE.transactions))
        for r, tx in enumerate(STORE.transactions):
            values = [
                tx.timestamp,
                tx.tx_type,
                tx.part_number,
                tx.lot_number,
                f"{tx.quantity_change:+d}",
                tx.location_from,
                tx.location_to,
                tx.operator,
                tx.reference,
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.table.setItem(r, c, item)


class SettingsView(BaseView):
    def __init__(self, toast: Callable[[str, str], None], operator_getter: Callable[[], str]) -> None:
        super().__init__("Settings", "Import, export, and backup tools.")
        self.toast = toast
        self.operator_getter = operator_getter
        self.service = ImportExportService(STORE)
        self.preview_kind = ""
        self.preview_path = ""
        self.preview_row_count = 0

        grid = QGridLayout()
        grid.setSpacing(16)
        self.root.addLayout(grid)

        export_card = Card("Export", "Write CSV snapshots to the exports folder.")
        export_btn = QPushButton("Export All")
        export_btn.setObjectName("SecondaryButton")
        export_btn.setMinimumHeight(50)
        export_btn.clicked.connect(self.export_all)
        self.export_summary = QLabel("No export yet.")
        self.export_summary.setObjectName("HelpText")
        export_card.layout.addWidget(export_btn)
        export_card.layout.addWidget(self.export_summary)
        grid.addWidget(export_card, 0, 0)

        backup_card = Card("Backup", "Create a manual SQLite database backup.")
        backup_btn = QPushButton("Create Backup")
        backup_btn.setObjectName("SecondaryButton")
        backup_btn.setMinimumHeight(50)
        backup_btn.clicked.connect(self.create_backup)
        self.backup_summary = QLabel("Startup backups run automatically.")
        self.backup_summary.setObjectName("HelpText")
        backup_card.layout.addWidget(backup_btn)
        backup_card.layout.addWidget(self.backup_summary)
        grid.addWidget(backup_card, 0, 1)

        import_card = Card("Import", "Preview row-level CSV issues before committing changes.")
        import_buttons = QHBoxLayout()
        for label, kind in [
            ("Choose Parts CSV", "parts"),
            ("Choose Inventory CSV", "inventory"),
            ("Choose BOM CSV", "bom"),
        ]:
            btn = QPushButton(label)
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda _, k=kind: self.choose_import(k))
            import_buttons.addWidget(btn)
        self.preview_summary = QLabel("Choose a CSV to preview.")
        self.preview_summary.setObjectName("HelpText")
        self.issue_table = QTableWidget(0, 4)
        self.issue_table.setHorizontalHeaderLabels(["Row", "Level", "Field", "Message"])
        self.issue_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.issue_table.verticalHeader().setVisible(False)
        self.commit_btn = QPushButton("Commit Import")
        self.commit_btn.setObjectName("SuccessButton")
        self.commit_btn.setMinimumHeight(50)
        self.commit_btn.setEnabled(False)
        self.commit_btn.clicked.connect(self.commit_import)
        import_card.layout.addLayout(import_buttons)
        import_card.layout.addWidget(self.preview_summary)
        import_card.layout.addWidget(self.issue_table)
        import_card.layout.addWidget(self.commit_btn)
        grid.addWidget(import_card, 1, 0, 1, 2)

        folders_card = Card("Folders", "Open generated exports or database backups.")
        folder_buttons = QHBoxLayout()
        exports_btn = QPushButton("Open Exports")
        backups_btn = QPushButton("Open Backups")
        exports_btn.clicked.connect(lambda: self.open_folder(EXPORT_DIR))
        backups_btn.clicked.connect(lambda: self.open_folder(BACKUP_DIR))
        folder_buttons.addWidget(exports_btn)
        folder_buttons.addWidget(backups_btn)
        folders_card.layout.addLayout(folder_buttons)
        grid.addWidget(folders_card, 2, 0, 1, 2)
        self.root.addStretch()

    def export_all(self) -> None:
        try:
            results = self.service.export_all()
            self.export_summary.setText(f"Exported {len(results)} files to {EXPORT_DIR}.")
            self.toast(f"Exported {len(results)} CSV files.", "success")
        except OSError as e:
            self.toast(f"Export failed: {e}", "error")

    def choose_import(self, kind: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Choose {kind} CSV", str(EXPORT_DIR), "CSV files (*.csv)")
        if not path:
            return
        self.preview_kind = kind
        self.preview_path = path
        try:
            preview = {
                "parts": self.service.preview_parts_import_csv,
                "inventory": self.service.preview_inventory_import_csv,
                "bom": self.service.preview_bom_import_csv,
            }[kind](path)
            self.preview_summary.setText(
                f"{kind.title()} preview — {path}: {preview.row_count} rows, {preview.valid_count} valid, "
                f"{len(preview.errors)} errors, {len(preview.warnings)} warnings."
            )
            self.preview_row_count = preview.row_count
            self.commit_btn.setEnabled(preview.can_import)
            self._show_issues(preview.errors + preview.warnings)
            if preview.errors:
                self.toast("CSV has validation errors.", "error")
            else:
                self.toast("CSV preview passed.", "success")
        except ValueError as e:
            self.commit_btn.setEnabled(False)
            self.toast(str(e), "error")

    def commit_import(self) -> None:
        if not self.preview_kind or not self.preview_path:
            self.toast("Choose a CSV first.", "error")
            return
        try:
            operator = self.operator_getter()
            answer = QMessageBox.question(
                self,
                "Confirm CSV import",
                f"Import {self.preview_row_count} {self.preview_kind} rows from {self.preview_path}? A backup will be created first.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            result = {
                "parts": self.service.import_parts_csv,
                "inventory": self.service.import_inventory_csv,
                "bom": self.service.import_bom_csv,
            }[self.preview_kind](self.preview_path, operator)
            self.toast(f"Imported {result.rows_imported} {result.kind} rows.", "success")
            self.commit_btn.setEnabled(False)
            self.preview_summary.setText(f"Imported {result.rows_imported} rows. Backup: {result.backup_path}")
        except ValueError as e:
            self.toast(str(e), "error")

    def create_backup(self) -> None:
        backup = backup_database(DB_PATH, BACKUP_DIR, reason="manual")
        if backup is None:
            self.toast("No database file exists to back up.", "error")
            return
        self.backup_summary.setText(str(backup))
        self.toast(f"Backup created: {backup.name}", "success")

    def open_folder(self, path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_issues(self, issues) -> None:
        self.issue_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            values = [str(issue.row_number), issue.level, issue.field, issue.message]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.issue_table.setItem(row, col, item)
