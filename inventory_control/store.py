from datetime import datetime
from typing import Callable, Dict, List

from inventory_control.models import Part, Shipment, Transaction


class InventoryStore:
    """Small in-memory store. Replace with SQLAlchemy services later."""

    def __init__(self) -> None:
        self.parts: Dict[str, Part] = {}
        self.balances: Dict[str, Dict[str, int]] = {}
        self.transactions: List[Transaction] = []
        self.shipments: List[Shipment] = []
        self.locations = ["Receiving", "Stock", "Shipping Bench", "Scrap"]
        self._shipment_counter = 1
        self._subscribers: List[Callable[[], None]] = []
        self.seed()

    def subscribe(self, callback: Callable[[], None]) -> None:
        self._subscribers.append(callback)

    def notify(self) -> None:
        for callback in self._subscribers:
            callback()

    def seed(self) -> None:
        self.add_part("ABC-123", "Bearing Assembly", minimum_quantity=5, notify=False)
        self.add_part("XYZ-999", "Control Cable", minimum_quantity=2, notify=False)
        self.receive("ABC-123", 12, "Stock", "System", "Seed", notify=False)
        self.receive("XYZ-999", 3, "Stock", "System", "Seed", notify=False)

    def now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def add_part(
        self,
        part_number: str,
        description: str,
        minimum_quantity: int = 0,
        location: str = "Stock",
        notify: bool = True,
    ) -> None:
        part_number = part_number.strip().upper()
        if not part_number:
            raise ValueError("Part number required.")
        if not description.strip():
            raise ValueError("Description required.")
        if part_number in self.parts:
            raise ValueError("Part already exists.")
        if minimum_quantity < 0:
            raise ValueError("Minimum quantity cannot be negative.")
        if location not in self.locations:
            raise ValueError("Invalid location.")
        self.parts[part_number] = Part(part_number, description.strip(), minimum_quantity, location)
        self.balances.setdefault(part_number, {loc: 0 for loc in self.locations})
        if notify:
            self.notify()

    def total_stock(self, part_number: str) -> int:
        return sum(self.balances.get(part_number, {}).values())

    def stock_at(self, part_number: str, location: str) -> int:
        return self.balances.get(part_number, {}).get(location, 0)

    def receive(
        self,
        part_number: str,
        qty: int,
        location: str,
        operator: str,
        reference: str = "",
        notes: str = "",
        notify: bool = True,
    ) -> None:
        self._require_part_location_qty(part_number, location, qty)
        self.balances[part_number][location] += qty
        self.transactions.insert(
            0,
            Transaction(self.now(), "RECEIVE", part_number, qty, "", location, operator, reference, notes),
        )
        if notify:
            self.notify()

    def ship(
        self,
        part_number: str,
        qty: int,
        location: str,
        recipient: str,
        operator: str,
        carrier: str = "",
        tracking: str = "",
        reference: str = "",
    ) -> str:
        self._require_part_location_qty(part_number, location, qty)
        if not recipient.strip():
            raise ValueError("Recipient required.")
        available = self.stock_at(part_number, location)
        if qty > available:
            raise ValueError(f"Not enough stock. Available: {available}, requested: {qty}.")
        shipment_number = self._next_shipment_number()
        self.balances[part_number][location] -= qty
        self.shipments.insert(
            0,
            Shipment(
                shipment_number,
                self.now(),
                part_number,
                qty,
                recipient.strip(),
                carrier.strip(),
                tracking.strip(),
            ),
        )
        self.transactions.insert(
            0,
            Transaction(self.now(), "SHIP", part_number, -qty, location, "", operator, reference or shipment_number),
        )
        self.notify()
        return shipment_number

    def move(self, part_number: str, qty: int, source: str, target: str, operator: str, reference: str = "") -> None:
        self._require_part_location_qty(part_number, source, qty)
        if target not in self.locations:
            raise ValueError("Invalid destination location.")
        if source == target:
            raise ValueError("Source and destination cannot match.")
        available = self.stock_at(part_number, source)
        if qty > available:
            raise ValueError(f"Not enough stock. Available: {available}, requested: {qty}.")
        self.balances[part_number][source] -= qty
        self.balances[part_number][target] += qty
        self.transactions.insert(0, Transaction(self.now(), "MOVE_OUT", part_number, -qty, source, target, operator, reference))
        self.transactions.insert(0, Transaction(self.now(), "MOVE_IN", part_number, qty, source, target, operator, reference))
        self.notify()

    def adjust(self, part_number: str, location: str, new_count: int, operator: str, reason: str) -> int:
        if new_count < 0:
            raise ValueError("New count cannot be negative.")
        if not reason.strip():
            raise ValueError("Reason required.")
        if part_number not in self.parts:
            raise ValueError("Part not found.")
        if location not in self.locations:
            raise ValueError("Invalid location.")
        old = self.stock_at(part_number, location)
        diff = new_count - old
        self.balances[part_number][location] = new_count
        self.transactions.insert(
            0,
            Transaction(self.now(), "COUNT_CORRECTION", part_number, diff, location, location, operator, reason.strip()),
        )
        self.notify()
        return diff

    def low_stock(self) -> List[Part]:
        return [
            p
            for p in self.parts.values()
            if p.minimum_quantity > 0 and self.total_stock(p.part_number) <= p.minimum_quantity
        ]

    def _next_shipment_number(self) -> str:
        number = f"SHP-{datetime.now().strftime('%Y%m%d')}-{self._shipment_counter:04d}"
        self._shipment_counter += 1
        return number

    def _require_part_location_qty(self, part_number: str, location: str, qty: int) -> None:
        if part_number not in self.parts:
            raise ValueError("Part not found.")
        if location not in self.locations:
            raise ValueError("Invalid location.")
        if qty <= 0:
            raise ValueError("Quantity must be greater than zero.")


STORE = InventoryStore()

