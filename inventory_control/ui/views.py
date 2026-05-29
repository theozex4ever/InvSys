from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from inventory_control.store import STORE
from inventory_control.ui.widgets import BaseView, Card, PartCombo, add_field


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
        self.total_parts.setText(str(len(STORE.parts)))
        self.total_stock.setText(str(sum(STORE.total_stock(p) for p in STORE.parts)))
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
        add = QPushButton("Add Part")
        add.setMinimumHeight(50)
        add.clicked.connect(self.add_part)
        add_field(form.layout, "Part number", self.part_number, required=True)
        add_field(form.layout, "Description", self.description, required=True)
        add_field(form.layout, "Minimum quantity", self.minimum)
        add_field(form.layout, "Default location", self.location)
        form.layout.addWidget(add)
        row.addWidget(form, 1)

        list_card = Card("Part List", "Search by number or description.")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search parts")
        self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Part", "Description", "Total", "Min"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        add_field(list_card.layout, "Search", self.search)
        list_card.layout.addWidget(self.table)
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
            self.part_number.clear()
            self.description.clear()
            self.minimum.setText("0")
        except ValueError as e:
            self.toast(str(e), "error")

    def refresh(self) -> None:
        query = self.search.text().lower().strip() if hasattr(self, "search") else ""
        rows = [p for p in STORE.parts.values() if query in p.part_number.lower() or query in p.description.lower()]
        self.table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            values = [p.part_number, p.description, str(STORE.total_stock(p.part_number)), str(p.minimum_quantity)]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.table.setItem(r, c, item)


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
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("PO, project, or note")
        self.preview = QLabel("Choose a part and quantity.")
        self.preview.setObjectName("HelpText")
        btn = QPushButton("Receive Stock")
        btn.setObjectName("SuccessButton")
        btn.setMinimumHeight(50)
        btn.clicked.connect(self.receive)
        add_field(card.layout, "Part", self.part, required=True)
        add_field(card.layout, "Quantity", self.qty, required=True)
        add_field(card.layout, "Location", self.location, required=True)
        add_field(card.layout, "Reference", self.reference, hint="Optional.")
        card.layout.addWidget(self.preview)
        card.layout.addWidget(btn)
        self.part.currentTextChanged.connect(self.update_preview)
        self.qty.textChanged.connect(self.update_preview)
        self.location.currentTextChanged.connect(self.update_preview)
        STORE.subscribe(self.refresh)

    def refresh(self) -> None:
        self.part.refresh()
        self.update_preview()

    def update_preview(self) -> None:
        pn = self.part.part_number()
        loc = self.location.currentText()
        stock = STORE.stock_at(pn, loc) if pn in STORE.parts else 0
        qty = int(self.qty.text() or 0)
        self.preview.setText(f"Current at {loc}: {stock}  ->  after receive: {stock + qty}")

    def receive(self) -> None:
        try:
            pn = self.part.part_number()
            qty = int(self.qty.text() or 0)
            loc = self.location.currentText()
            STORE.receive(pn, qty, loc, self.operator_getter(), self.reference.text())
            self.toast(f"Received {qty} {pn}. New stock in {loc}: {STORE.stock_at(pn, loc)}.", "success")
            self.qty.clear()
            self.reference.clear()
        except ValueError as e:
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
        self.recipient = QLineEdit()
        self.recipient.setPlaceholderText("Project, customer, or recipient")
        self.carrier = QLineEdit()
        self.carrier.setPlaceholderText("UPS, FedEx, handoff")
        self.tracking = QLineEdit()
        self.tracking.setPlaceholderText("Tracking number")
        self.preview = QLabel("Choose a part and quantity.")
        self.preview.setObjectName("HelpText")
        btn = QPushButton("Ship Stock")
        btn.setObjectName("DangerButton")
        btn.setMinimumHeight(50)
        btn.clicked.connect(self.ship)
        add_field(card.layout, "Part", self.part, required=True)
        add_field(card.layout, "Quantity", self.qty, required=True)
        add_field(card.layout, "Location", self.location, required=True)
        add_field(card.layout, "Recipient / project", self.recipient, required=True)
        add_field(card.layout, "Carrier", self.carrier, hint="Optional.")
        add_field(card.layout, "Tracking number", self.tracking, hint="Optional.")
        card.layout.addWidget(self.preview)
        card.layout.addWidget(btn)
        self.part.currentTextChanged.connect(self.update_preview)
        self.qty.textChanged.connect(self.update_preview)
        self.location.currentTextChanged.connect(self.update_preview)
        STORE.subscribe(self.refresh)

    def refresh(self) -> None:
        self.part.refresh()
        self.update_preview()

    def update_preview(self) -> None:
        pn = self.part.part_number()
        loc = self.location.currentText()
        stock = STORE.stock_at(pn, loc) if pn in STORE.parts else 0
        qty = int(self.qty.text() or 0)
        after = stock - qty
        marker = "OK" if after >= 0 else "Blocked"
        self.preview.setText(f"{marker}: available at {loc}: {stock}  ->  after ship: {after}")

    def ship(self) -> None:
        try:
            pn = self.part.part_number()
            qty = int(self.qty.text() or 0)
            loc = self.location.currentText()
            sn = STORE.ship(
                pn,
                qty,
                loc,
                self.recipient.text(),
                self.operator_getter(),
                self.carrier.text(),
                self.tracking.text(),
            )
            self.toast(f"Shipped {qty} of {pn}. Shipment: {sn}.", "success")
            self.qty.clear()
            self.recipient.clear()
            self.carrier.clear()
            self.tracking.clear()
        except ValueError as e:
            self.toast(str(e), "error")


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
        self.move_to = QComboBox()
        self.move_to.addItems(STORE.locations)
        self.move_to.setCurrentText("Shipping Bench")
        move_btn = QPushButton("Move Stock")
        move_btn.setMinimumHeight(50)
        move_btn.clicked.connect(self.move_stock)
        add_field(move.layout, "Part", self.move_part, required=True)
        add_field(move.layout, "Quantity", self.move_qty, required=True)
        add_field(move.layout, "From", self.move_from, required=True)
        add_field(move.layout, "To", self.move_to, required=True)
        move.layout.addWidget(move_btn)
        row.addWidget(move)

        adjust = Card("Adjust Count", "Requires a reason. Keeps the audit trail.")
        self.adjust_part = PartCombo()
        self.adjust_count = QLineEdit()
        self.adjust_count.setValidator(QIntValidator(0, 999999))
        self.adjust_count.setPlaceholderText("New counted quantity")
        self.adjust_location = QComboBox()
        self.adjust_location.addItems(STORE.locations)
        self.adjust_location.setCurrentText("Stock")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Why the count changed")
        adjust_btn = QPushButton("Correct Count")
        adjust_btn.setObjectName("SecondaryButton")
        adjust_btn.setMinimumHeight(50)
        adjust_btn.clicked.connect(self.adjust_stock)
        add_field(adjust.layout, "Part", self.adjust_part, required=True)
        add_field(adjust.layout, "New counted quantity", self.adjust_count, required=True)
        add_field(adjust.layout, "Location", self.adjust_location, required=True)
        add_field(adjust.layout, "Reason", self.reason, required=True)
        adjust.layout.addWidget(adjust_btn)
        row.addWidget(adjust)
        STORE.subscribe(self.refresh)

    def refresh(self) -> None:
        self.move_part.refresh()
        self.adjust_part.refresh()

    def move_stock(self) -> None:
        try:
            STORE.move(
                self.move_part.part_number(),
                int(self.move_qty.text() or 0),
                self.move_from.currentText(),
                self.move_to.currentText(),
                self.operator_getter(),
            )
            self.toast("Stock moved.", "success")
            self.move_qty.clear()
        except ValueError as e:
            self.toast(str(e), "error")

    def adjust_stock(self) -> None:
        try:
            diff = STORE.adjust(
                self.adjust_part.part_number(),
                self.adjust_location.currentText(),
                int(self.adjust_count.text() or 0),
                self.operator_getter(),
                self.reason.text(),
            )
            self.toast(f"Count corrected. Difference: {diff:+d}.", "success")
            self.adjust_count.clear()
            self.reason.clear()
        except ValueError as e:
            self.toast(str(e), "error")


class HistoryView(BaseView):
    def __init__(self) -> None:
        super().__init__("History", "Trace inventory activity. No hidden changes.")
        card = Card("Transactions")
        self.root.addWidget(card)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Time", "Type", "Part", "Qty", "From", "To", "Operator", "Reference"])
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

