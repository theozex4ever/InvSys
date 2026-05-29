from datetime import datetime
from typing import Callable, Dict, List

from inventory_control.models import (
    BOMComponent,
    BOMRequirement,
    BOMTreeNode,
    ComponentConsumption,
    Part,
    Shipment,
    Transaction,
)


class InventoryStore:
    """Small in-memory store. Replace with SQLAlchemy services later."""

    def __init__(self) -> None:
        self.parts: Dict[str, Part] = {}
        self.balances: Dict[str, Dict[str, int]] = {}
        self.bom_components: Dict[str, Dict[str, int]] = {}
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
        part_number = self._normalize_part_number(part_number)
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

    def add_bom_component(
        self,
        parent_part_number: str,
        component_part_number: str,
        quantity_per: int,
        notify: bool = True,
    ) -> None:
        parent = self._normalize_part_number(parent_part_number)
        component = self._normalize_part_number(component_part_number)
        self._require_part(parent)
        self._require_part(component)
        if parent == component:
            raise ValueError("A part cannot contain itself.")
        if quantity_per <= 0:
            raise ValueError("Component quantity must be greater than zero.")
        if self._bom_contains(component, parent):
            raise ValueError("This component would create a circular BOM.")
        self.bom_components.setdefault(parent, {})[component] = quantity_per
        if notify:
            self.notify()

    def remove_bom_component(self, parent_part_number: str, component_part_number: str, notify: bool = True) -> None:
        parent = self._normalize_part_number(parent_part_number)
        component = self._normalize_part_number(component_part_number)
        self._require_part(parent)
        self._require_part(component)
        if component not in self.bom_components.get(parent, {}):
            raise ValueError("Component is not on this BOM.")
        del self.bom_components[parent][component]
        if not self.bom_components[parent]:
            del self.bom_components[parent]
        if notify:
            self.notify()

    def has_bom(self, part_number: str) -> bool:
        return bool(self.bom_components.get(self._normalize_part_number(part_number)))

    def bom_children(self, part_number: str) -> List[BOMComponent]:
        parent = self._normalize_part_number(part_number)
        return [
            BOMComponent(parent, component, quantity_per)
            for component, quantity_per in sorted(self.bom_components.get(parent, {}).items())
        ]

    def bom_requirements(self, part_number: str, qty: int, location: str) -> List[BOMRequirement]:
        part_number = self._normalize_part_number(part_number)
        self._require_part_location_qty(part_number, location, qty)
        if not self.has_bom(part_number):
            return []
        requirements = self._leaf_requirements(part_number, qty)
        return [
            BOMRequirement(
                component,
                self.parts[component].description,
                required,
                self.stock_at(component, location),
                max(required - self.stock_at(component, location), 0),
            )
            for component, required in sorted(requirements.items())
        ]

    def bom_tree(self, part_number: str, qty: int = 1, location: str = "Stock") -> BOMTreeNode:
        part_number = self._normalize_part_number(part_number)
        self._require_part(part_number)
        if location not in self.locations:
            raise ValueError("Invalid location.")
        if qty <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return self._bom_tree_node(part_number, qty, 1, location)

    def bom_can_ship(self, part_number: str, qty: int, location: str) -> bool:
        return all(req.shortage == 0 for req in self.bom_requirements(part_number, qty, location))

    def total_stock(self, part_number: str) -> int:
        part_number = self._normalize_part_number(part_number)
        return sum(self.balances.get(part_number, {}).values())

    def stock_at(self, part_number: str, location: str) -> int:
        part_number = self._normalize_part_number(part_number)
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
        part_number = self._normalize_part_number(part_number)
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
        part_number = self._normalize_part_number(part_number)
        self._require_part_location_qty(part_number, location, qty)
        if not recipient.strip():
            raise ValueError("Recipient required.")
        if self.has_bom(part_number):
            return self._ship_bom_part(
                part_number,
                qty,
                location,
                recipient,
                operator,
                carrier,
                tracking,
                reference,
            )
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
        part_number = self._normalize_part_number(part_number)
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
        part_number = self._normalize_part_number(part_number)
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

    def _ship_bom_part(
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
        requirements = self.bom_requirements(part_number, qty, location)
        shortages = [req for req in requirements if req.shortage > 0]
        if shortages:
            details = "; ".join(
                f"{req.part_number}: available {req.stock_available}, required {req.quantity_required}"
                for req in shortages
            )
            raise ValueError(f"Not enough BOM component stock for {part_number}. {details}.")

        shipment_number = self._next_shipment_number()
        timestamp = self.now()
        consumed = [
            ComponentConsumption(req.part_number, req.quantity_required, location)
            for req in requirements
        ]

        for req in requirements:
            self.balances[req.part_number][location] -= req.quantity_required
            self.transactions.insert(
                0,
                Transaction(
                    timestamp,
                    "BOM_CONSUME",
                    req.part_number,
                    -req.quantity_required,
                    location,
                    "",
                    operator,
                    shipment_number,
                    f"Used by {part_number} x{qty}",
                ),
            )

        self.shipments.insert(
            0,
            Shipment(
                shipment_number,
                timestamp,
                part_number,
                qty,
                recipient.strip(),
                carrier.strip(),
                tracking.strip(),
                consumed,
            ),
        )
        notes = "Shipment fulfilled by BOM component consumption."
        if reference.strip():
            notes = f"{notes} Reference: {reference.strip()}"
        self.transactions.insert(
            0,
            Transaction(
                timestamp,
                "SHIP_BOM",
                part_number,
                -qty,
                location,
                "",
                operator,
                shipment_number,
                notes,
            ),
        )
        self.notify()
        return shipment_number

    def _require_part_location_qty(self, part_number: str, location: str, qty: int) -> None:
        self._require_part(part_number)
        if location not in self.locations:
            raise ValueError("Invalid location.")
        if qty <= 0:
            raise ValueError("Quantity must be greater than zero.")

    def _require_part(self, part_number: str) -> None:
        if part_number not in self.parts:
            raise ValueError("Part not found.")

    def _normalize_part_number(self, part_number: str) -> str:
        return part_number.strip().upper()

    def _bom_contains(self, start_part_number: str, target_part_number: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if start_part_number in seen:
            return False
        seen.add(start_part_number)
        for child in self.bom_components.get(start_part_number, {}):
            if child == target_part_number or self._bom_contains(child, target_part_number, seen):
                return True
        return False

    def _leaf_requirements(self, part_number: str, qty: int) -> Dict[str, int]:
        children = self.bom_components.get(part_number, {})
        if not children:
            return {part_number: qty}
        requirements: Dict[str, int] = {}
        for component, quantity_per in children.items():
            child_requirements = self._leaf_requirements(component, qty * quantity_per)
            for leaf, required in child_requirements.items():
                requirements[leaf] = requirements.get(leaf, 0) + required
        return requirements

    def _bom_tree_node(
        self,
        part_number: str,
        qty_required: int,
        quantity_per_parent: int,
        location: str,
    ) -> BOMTreeNode:
        children = [
            self._bom_tree_node(component, qty_required * quantity_per, quantity_per, location)
            for component, quantity_per in sorted(self.bom_components.get(part_number, {}).items())
        ]
        return BOMTreeNode(
            part_number,
            self.parts[part_number].description,
            qty_required,
            quantity_per_parent,
            self.stock_at(part_number, location),
            children,
        )


STORE = InventoryStore()
