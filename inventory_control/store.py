from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List

from sqlalchemy import desc, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from inventory_control.db import create_inventory_engine, create_session_factory
from inventory_control.migrations import bootstrap_database
from inventory_control.models import (
    BOMComponent,
    BOMRequirement,
    BOMTreeNode,
    ComponentConsumption,
    Lot,
    LotAllocation,
    LotBalance,
    Part,
    Shipment,
    Transaction,
)
from inventory_control.orm import (
    BOMComponentRecord,
    InventoryBalanceRecord,
    InventoryTransactionRecord,
    LocationRecord,
    LotRecord,
    PartRecord,
    ShipmentComponentRecord,
    ShipmentRecord,
)


class InventoryStore:
    """SQLite-backed inventory store with the original UI-facing API shape."""

    def __init__(self, db_path: str | Path | None = ":memory:", seed: bool = True) -> None:
        self.engine: Engine = create_inventory_engine(db_path)
        bootstrap_database(self.engine)
        self.session_factory: sessionmaker[Session] = create_session_factory(self.engine)
        self._subscribers: List[Callable[[], None]] = []
        if seed:
            self.seed()

    @property
    def parts(self) -> Dict[str, Part]:
        with self.session_factory() as session:
            rows = session.scalars(select(PartRecord).order_by(PartRecord.part_number)).all()
            return {row.part_number: self._part_dto(row) for row in rows}

    @property
    def locations(self) -> List[str]:
        with self.session_factory() as session:
            return list(session.scalars(select(LocationRecord.name).where(LocationRecord.active.is_(True)).order_by(LocationRecord.id)))

    @property
    def balances(self) -> Dict[str, Dict[str, int]]:
        with self.session_factory() as session:
            result: Dict[str, Dict[str, int]] = {
                part.part_number: {location: 0 for location in self.locations}
                for part in session.scalars(select(PartRecord)).all()
            }
            rows = session.execute(
                select(
                    PartRecord.part_number,
                    LocationRecord.name,
                    func.sum(InventoryBalanceRecord.quantity),
                )
                .join(InventoryBalanceRecord.part)
                .join(InventoryBalanceRecord.location)
                .group_by(PartRecord.part_number, LocationRecord.name)
            ).all()
            for part_number, location, qty in rows:
                result.setdefault(part_number, {})[location] = int(qty or 0)
            return result

    @property
    def bom_components(self) -> Dict[str, Dict[str, int]]:
        with self.session_factory() as session:
            rows = session.scalars(select(BOMComponentRecord)).all()
            result: Dict[str, Dict[str, int]] = {}
            for row in rows:
                result.setdefault(row.parent_part.part_number, {})[row.component_part.part_number] = row.quantity_per
            return result

    @property
    def transactions(self) -> List[Transaction]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(InventoryTransactionRecord).order_by(desc(InventoryTransactionRecord.id))
            ).all()
            return [self._transaction_dto(row) for row in rows]

    @property
    def shipments(self) -> List[Shipment]:
        with self.session_factory() as session:
            rows = session.scalars(select(ShipmentRecord).order_by(desc(ShipmentRecord.id))).all()
            return [self._shipment_dto(row) for row in rows]

    def subscribe(self, callback: Callable[[], None]) -> None:
        self._subscribers.append(callback)

    def notify(self) -> None:
        for callback in self._subscribers:
            callback()

    def seed(self) -> None:
        if self.parts:
            return
        self.add_part("ABC-123", "Bearing Assembly", minimum_quantity=5, notify=False)
        self.add_part("XYZ-999", "Control Cable", minimum_quantity=2, notify=False)
        self.receive("ABC-123", 12, "Stock", "SEED", "System", "Seed", notify=False)
        self.receive("XYZ-999", 3, "Stock", "SEED", "System", "Seed", notify=False)

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
        if minimum_quantity < 0:
            raise ValueError("Minimum quantity cannot be negative.")
        with self.session_factory.begin() as session:
            if self._part(session, part_number) is not None:
                raise ValueError("Part already exists.")
            location_row = self._require_location(session, location)
            now = self.now()
            session.add(
                PartRecord(
                    part_number=part_number,
                    description=description.strip(),
                    minimum_quantity=minimum_quantity,
                    default_location_id=location_row.id,
                    active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
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
        if parent == component:
            raise ValueError("A part cannot contain itself.")
        if quantity_per <= 0:
            raise ValueError("Component quantity must be greater than zero.")
        with self.session_factory.begin() as session:
            parent_part = self._require_part(session, parent)
            component_part = self._require_part(session, component)
            if self._bom_contains(session, component, parent):
                raise ValueError("This component would create a circular BOM.")
            row = session.scalar(
                select(BOMComponentRecord).where(
                    BOMComponentRecord.parent_part_id == parent_part.id,
                    BOMComponentRecord.component_part_id == component_part.id,
                )
            )
            if row is None:
                session.add(
                    BOMComponentRecord(
                        parent_part_id=parent_part.id,
                        component_part_id=component_part.id,
                        quantity_per=quantity_per,
                    )
                )
            else:
                row.quantity_per = quantity_per
        if notify:
            self.notify()

    def remove_bom_component(self, parent_part_number: str, component_part_number: str, notify: bool = True) -> None:
        parent = self._normalize_part_number(parent_part_number)
        component = self._normalize_part_number(component_part_number)
        with self.session_factory.begin() as session:
            parent_part = self._require_part(session, parent)
            component_part = self._require_part(session, component)
            row = session.scalar(
                select(BOMComponentRecord).where(
                    BOMComponentRecord.parent_part_id == parent_part.id,
                    BOMComponentRecord.component_part_id == component_part.id,
                )
            )
            if row is None:
                raise ValueError("Component is not on this BOM.")
            session.delete(row)
        if notify:
            self.notify()

    def has_bom(self, part_number: str) -> bool:
        parent = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            part = self._part(session, parent)
            if part is None:
                return False
            return session.scalar(
                select(BOMComponentRecord.id).where(BOMComponentRecord.parent_part_id == part.id).limit(1)
            ) is not None

    def bom_children(self, part_number: str) -> List[BOMComponent]:
        parent = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            part = self._part(session, parent)
            if part is None:
                return []
            rows = session.scalars(
                select(BOMComponentRecord)
                .where(BOMComponentRecord.parent_part_id == part.id)
                .join(BOMComponentRecord.component_part)
                .order_by(PartRecord.part_number)
            ).all()
            return [
                BOMComponent(parent, row.component_part.part_number, row.quantity_per)
                for row in rows
            ]

    def bom_requirements(self, part_number: str, qty: int, location: str) -> List[BOMRequirement]:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            self._require_part_location_qty(session, part_number, location, qty)
            if not self._has_bom(session, part_number):
                return []
            requirements = self._leaf_requirements(session, part_number, qty)
            return [
                BOMRequirement(
                    component,
                    self._require_part(session, component).description,
                    required,
                    self.stock_at(component, location),
                    max(required - self.stock_at(component, location), 0),
                )
                for component, required in sorted(requirements.items())
            ]

    def bom_tree(self, part_number: str, qty: int = 1, location: str = "Stock") -> BOMTreeNode:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            self._require_part(session, part_number)
            self._require_location(session, location)
            if qty <= 0:
                raise ValueError("Quantity must be greater than zero.")
            return self._bom_tree_node(session, part_number, qty, 1, location)

    def bom_can_ship(self, part_number: str, qty: int, location: str) -> bool:
        return all(req.shortage == 0 for req in self.bom_requirements(part_number, qty, location))

    def total_stock(self, part_number: str) -> int:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            part = self._part(session, part_number)
            if part is None:
                return 0
            total = session.scalar(
                select(func.sum(InventoryBalanceRecord.quantity)).where(InventoryBalanceRecord.part_id == part.id)
            )
            return int(total or 0)

    def stock_at(self, part_number: str, location: str, lot_number: str | None = None) -> int:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            part = self._part(session, part_number)
            loc = self._location(session, location)
            if part is None or loc is None:
                return 0
            stmt = select(func.sum(InventoryBalanceRecord.quantity)).where(
                InventoryBalanceRecord.part_id == part.id,
                InventoryBalanceRecord.location_id == loc.id,
            )
            if lot_number is not None:
                lot = self._lot(session, part.id, lot_number)
                if lot is None:
                    return 0
                stmt = stmt.where(InventoryBalanceRecord.lot_id == lot.id)
            return int(session.scalar(stmt) or 0)

    def lots_for_part(self, part_number: str, location: str | None = None, positive_only: bool = False) -> List[Lot]:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            part = self._part(session, part_number)
            if part is None:
                return []
            stmt = select(LotRecord).where(LotRecord.part_id == part.id).order_by(LotRecord.lot_number)
            if location is not None or positive_only:
                stmt = stmt.join(InventoryBalanceRecord, InventoryBalanceRecord.lot_id == LotRecord.id)
                if location is not None:
                    loc = self._location(session, location)
                    if loc is None:
                        return []
                    stmt = stmt.where(InventoryBalanceRecord.location_id == loc.id)
                if positive_only:
                    stmt = stmt.where(InventoryBalanceRecord.quantity > 0)
            rows = session.scalars(stmt).unique().all()
            return [Lot(part_number, row.lot_number, row.active) for row in rows]

    def lot_balances(self, part_number: str, location: str | None = None) -> List[LotBalance]:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory() as session:
            part = self._part(session, part_number)
            if part is None:
                return []
            stmt = (
                select(InventoryBalanceRecord)
                .where(InventoryBalanceRecord.part_id == part.id)
                .join(InventoryBalanceRecord.location)
                .join(InventoryBalanceRecord.lot)
                .order_by(LocationRecord.name, LotRecord.lot_number)
            )
            if location is not None:
                loc = self._location(session, location)
                if loc is None:
                    return []
                stmt = stmt.where(InventoryBalanceRecord.location_id == loc.id)
            rows = session.scalars(stmt).all()
            return [
                LotBalance(part_number, row.lot.lot_number, row.location.name, row.quantity)
                for row in rows
            ]

    def receive(
        self,
        part_number: str,
        qty: int,
        location: str,
        lot_number: str,
        operator: str,
        reference: str = "",
        notes: str = "",
        notify: bool = True,
    ) -> None:
        part_number = self._normalize_part_number(part_number)
        lot_number = self._normalize_lot_number(lot_number)
        with self.session_factory.begin() as session:
            part, loc = self._require_part_location_qty(session, part_number, location, qty)
            lot = self._get_or_create_lot(session, part, lot_number)
            balance = self._get_or_create_balance(session, part, loc, lot)
            balance.quantity += qty
            balance.updated_at = self.now()
            self._add_transaction(session, "RECEIVE", part, qty, None, loc, operator, reference, notes, lot)
        if notify:
            self.notify()

    def ship(
        self,
        part_number: str,
        qty: int,
        location: str,
        recipient: str,
        operator: str,
        lot_number: str | None = None,
        component_lots: List[LotAllocation] | None = None,
        carrier: str = "",
        tracking: str = "",
        reference: str = "",
    ) -> str:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory.begin() as session:
            part, loc = self._require_part_location_qty(session, part_number, location, qty)
            if not recipient.strip():
                raise ValueError("Recipient required.")
            if self._has_bom(session, part_number):
                shipment_number = self._ship_bom_part(
                    session,
                    part,
                    qty,
                    loc,
                    recipient,
                    operator,
                    component_lots,
                    carrier,
                    tracking,
                    reference,
                )
            else:
                if lot_number is None:
                    raise ValueError("Lot required.")
                lot = self._require_lot(session, part.id, lot_number)
                available = self._stock_at(session, part.id, loc.id, lot.id)
                if qty > available:
                    raise ValueError(f"Not enough stock. Available: {available}, requested: {qty}.")
                shipment_number = self._next_shipment_number(session)
                shipment = ShipmentRecord(
                    shipment_number=shipment_number,
                    timestamp=self.now(),
                    part_id=part.id,
                    quantity=qty,
                    recipient=recipient.strip(),
                    carrier=carrier.strip(),
                    tracking_number=tracking.strip(),
                    reference=reference.strip(),
                )
                session.add(shipment)
                session.flush()
                balance = self._require_balance(session, part, loc, lot)
                balance.quantity -= qty
                balance.updated_at = self.now()
                self._add_transaction(
                    session,
                    "SHIP",
                    part,
                    -qty,
                    loc,
                    None,
                    operator,
                    reference or shipment_number,
                    "",
                    lot,
                    shipment.id,
                )
        self.notify()
        return shipment_number

    def move(
        self,
        part_number: str,
        qty: int,
        source: str,
        target: str,
        lot_number: str,
        operator: str,
        reference: str = "",
    ) -> None:
        part_number = self._normalize_part_number(part_number)
        with self.session_factory.begin() as session:
            part, source_loc = self._require_part_location_qty(session, part_number, source, qty)
            target_loc = self._require_location(session, target, destination=True)
            if source == target:
                raise ValueError("Source and destination cannot match.")
            lot = self._require_lot(session, part.id, lot_number)
            available = self._stock_at(session, part.id, source_loc.id, lot.id)
            if qty > available:
                raise ValueError(f"Not enough stock. Available: {available}, requested: {qty}.")
            source_balance = self._require_balance(session, part, source_loc, lot)
            target_balance = self._get_or_create_balance(session, part, target_loc, lot)
            source_balance.quantity -= qty
            target_balance.quantity += qty
            now = self.now()
            source_balance.updated_at = now
            target_balance.updated_at = now
            self._add_transaction(session, "MOVE_OUT", part, -qty, source_loc, target_loc, operator, reference, "", lot)
            self._add_transaction(session, "MOVE_IN", part, qty, source_loc, target_loc, operator, reference, "", lot)
        self.notify()

    def adjust(self, part_number: str, location: str, lot_number: str, new_count: int, operator: str, reason: str) -> int:
        part_number = self._normalize_part_number(part_number)
        if new_count < 0:
            raise ValueError("New count cannot be negative.")
        if not reason.strip():
            raise ValueError("Reason required.")
        with self.session_factory.begin() as session:
            part = self._require_part(session, part_number)
            loc = self._require_location(session, location)
            lot = self._require_lot(session, part.id, lot_number)
            balance = self._get_or_create_balance(session, part, loc, lot)
            old = balance.quantity
            diff = new_count - old
            balance.quantity = new_count
            balance.updated_at = self.now()
            self._add_transaction(session, "COUNT_CORRECTION", part, diff, loc, loc, operator, reason.strip(), "", lot)
        self.notify()
        return diff

    def low_stock(self) -> List[Part]:
        return [
            p
            for p in self.parts.values()
            if p.minimum_quantity > 0 and self.total_stock(p.part_number) <= p.minimum_quantity
        ]

    def _ship_bom_part(
        self,
        session: Session,
        part: PartRecord,
        qty: int,
        location: LocationRecord,
        recipient: str,
        operator: str,
        component_lots: List[LotAllocation] | None,
        carrier: str = "",
        tracking: str = "",
        reference: str = "",
    ) -> str:
        if not component_lots:
            raise ValueError("Component lot selections required.")

        requirements = self._leaf_requirements(session, part.part_number, qty)
        expected = {(part_number, location.name): required for part_number, required in requirements.items()}
        allocations = self._aggregate_allocations(component_lots)
        if allocations != expected:
            raise ValueError("Component lot selections must exactly match BOM requirements.")

        for allocation in component_lots:
            component_part = self._require_part(session, allocation.part_number)
            component_location = self._require_location(session, allocation.location)
            lot = self._lot(session, component_part.id, allocation.lot_number)
            available = self._stock_at(session, component_part.id, component_location.id, lot.id) if lot else 0
            if allocation.quantity > available:
                raise ValueError(
                    f"Not enough BOM component stock for {part.part_number}. "
                    f"{component_part.part_number} lot {self._normalize_lot_number(allocation.lot_number)}: available {available}, "
                    f"required {allocation.quantity}."
                )

        shipment_number = self._next_shipment_number(session)
        timestamp = self.now()
        shipment = ShipmentRecord(
            shipment_number=shipment_number,
            timestamp=timestamp,
            part_id=part.id,
            quantity=qty,
            recipient=recipient.strip(),
            carrier=carrier.strip(),
            tracking_number=tracking.strip(),
            reference=reference.strip(),
        )
        session.add(shipment)
        session.flush()

        for allocation in component_lots:
            component_part = self._require_part(session, allocation.part_number)
            component_location = self._require_location(session, allocation.location)
            lot = self._require_lot(session, component_part.id, allocation.lot_number)
            balance = self._require_balance(session, component_part, component_location, lot)
            balance.quantity -= allocation.quantity
            balance.updated_at = timestamp
            session.add(
                ShipmentComponentRecord(
                    shipment_id=shipment.id,
                    part_id=component_part.id,
                    lot_id=lot.id,
                    location_id=component_location.id,
                    quantity=allocation.quantity,
                )
            )
            self._add_transaction(
                session,
                "BOM_CONSUME",
                component_part,
                -allocation.quantity,
                component_location,
                None,
                operator,
                shipment_number,
                f"Used by {part.part_number} x{qty}",
                lot,
                shipment.id,
                timestamp,
            )

        notes = "Shipment fulfilled by BOM component consumption."
        if reference.strip():
            notes = f"{notes} Reference: {reference.strip()}"
        self._add_transaction(
            session,
            "SHIP_BOM",
            part,
            -qty,
            location,
            None,
            operator,
            shipment_number,
            notes,
            None,
            shipment.id,
            timestamp,
        )
        return shipment_number

    def _aggregate_allocations(self, allocations: Iterable[LotAllocation]) -> Dict[tuple[str, str], int]:
        result: Dict[tuple[str, str], int] = {}
        for allocation in allocations:
            if allocation.quantity <= 0:
                raise ValueError("Component lot quantity must be greater than zero.")
            key = (self._normalize_part_number(allocation.part_number), allocation.location)
            result[key] = result.get(key, 0) + allocation.quantity
        return result

    def _next_shipment_number(self, session: Session) -> str:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"SHP-{today}-"
        last = session.scalar(
            select(ShipmentRecord.shipment_number)
            .where(ShipmentRecord.shipment_number.like(f"{prefix}%"))
            .order_by(desc(ShipmentRecord.shipment_number))
            .limit(1)
        )
        counter = int(last.split("-")[-1]) + 1 if last else 1
        return f"{prefix}{counter:04d}"

    def _require_part_location_qty(
        self,
        session: Session,
        part_number: str,
        location: str,
        qty: int,
    ) -> tuple[PartRecord, LocationRecord]:
        part = self._require_part(session, part_number)
        loc = self._require_location(session, location)
        if qty <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return part, loc

    def _require_part(self, session: Session, part_number: str) -> PartRecord:
        part = self._part(session, part_number)
        if part is None:
            raise ValueError("Part not found.")
        return part

    def _part(self, session: Session, part_number: str) -> PartRecord | None:
        return session.scalar(select(PartRecord).where(PartRecord.part_number == self._normalize_part_number(part_number)))

    def _require_location(self, session: Session, location: str, destination: bool = False) -> LocationRecord:
        loc = self._location(session, location)
        if loc is None:
            raise ValueError("Invalid destination location." if destination else "Invalid location.")
        return loc

    def _location(self, session: Session, location: str) -> LocationRecord | None:
        return session.scalar(select(LocationRecord).where(LocationRecord.name == location))

    def _require_lot(self, session: Session, part_id: int, lot_number: str) -> LotRecord:
        lot_number = self._normalize_lot_number(lot_number)
        lot = self._lot(session, part_id, lot_number)
        if lot is None:
            raise ValueError("Lot not found.")
        return lot

    def _lot(self, session: Session, part_id: int, lot_number: str) -> LotRecord | None:
        lot_number = self._normalize_lot_number(lot_number)
        return session.scalar(select(LotRecord).where(LotRecord.part_id == part_id, LotRecord.lot_number == lot_number))

    def _get_or_create_lot(self, session: Session, part: PartRecord, lot_number: str) -> LotRecord:
        lot = self._lot(session, part.id, lot_number)
        if lot is None:
            lot = LotRecord(part_id=part.id, lot_number=self._normalize_lot_number(lot_number), active=True, created_at=self.now())
            session.add(lot)
            session.flush()
        return lot

    def _require_balance(
        self,
        session: Session,
        part: PartRecord,
        location: LocationRecord,
        lot: LotRecord,
    ) -> InventoryBalanceRecord:
        balance = self._balance(session, part.id, location.id, lot.id)
        if balance is None:
            raise ValueError("Not enough stock. Available: 0, requested: 1.")
        return balance

    def _get_or_create_balance(
        self,
        session: Session,
        part: PartRecord,
        location: LocationRecord,
        lot: LotRecord,
    ) -> InventoryBalanceRecord:
        balance = self._balance(session, part.id, location.id, lot.id)
        if balance is None:
            balance = InventoryBalanceRecord(
                part_id=part.id,
                location_id=location.id,
                lot_id=lot.id,
                quantity=0,
                updated_at=self.now(),
            )
            session.add(balance)
            session.flush()
        return balance

    def _balance(self, session: Session, part_id: int, location_id: int, lot_id: int) -> InventoryBalanceRecord | None:
        return session.scalar(
            select(InventoryBalanceRecord).where(
                InventoryBalanceRecord.part_id == part_id,
                InventoryBalanceRecord.location_id == location_id,
                InventoryBalanceRecord.lot_id == lot_id,
            )
        )

    def _stock_at(self, session: Session, part_id: int, location_id: int, lot_id: int) -> int:
        return int(
            session.scalar(
                select(func.sum(InventoryBalanceRecord.quantity)).where(
                    InventoryBalanceRecord.part_id == part_id,
                    InventoryBalanceRecord.location_id == location_id,
                    InventoryBalanceRecord.lot_id == lot_id,
                )
            )
            or 0
        )

    def _add_transaction(
        self,
        session: Session,
        tx_type: str,
        part: PartRecord,
        quantity_change: int,
        location_from: LocationRecord | None,
        location_to: LocationRecord | None,
        operator: str,
        reference: str = "",
        notes: str = "",
        lot: LotRecord | None = None,
        shipment_id: int | None = None,
        timestamp: str | None = None,
    ) -> None:
        session.add(
            InventoryTransactionRecord(
                timestamp=timestamp or self.now(),
                tx_type=tx_type,
                part_id=part.id,
                lot_id=lot.id if lot else None,
                quantity_change=quantity_change,
                location_from_id=location_from.id if location_from else None,
                location_to_id=location_to.id if location_to else None,
                operator=operator,
                reference=reference.strip(),
                notes=notes.strip(),
                shipment_id=shipment_id,
            )
        )

    def _has_bom(self, session: Session, part_number: str) -> bool:
        part = self._part(session, part_number)
        if part is None:
            return False
        return session.scalar(
            select(BOMComponentRecord.id).where(BOMComponentRecord.parent_part_id == part.id).limit(1)
        ) is not None

    def _bom_contains(self, session: Session, start_part_number: str, target_part_number: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if start_part_number in seen:
            return False
        seen.add(start_part_number)
        start = self._part(session, start_part_number)
        if start is None:
            return False
        children = session.scalars(
            select(BOMComponentRecord).where(BOMComponentRecord.parent_part_id == start.id)
        ).all()
        for child in children:
            child_number = child.component_part.part_number
            if child_number == target_part_number or self._bom_contains(session, child_number, target_part_number, seen):
                return True
        return False

    def _leaf_requirements(self, session: Session, part_number: str, qty: int) -> Dict[str, int]:
        part = self._require_part(session, part_number)
        children = session.scalars(
            select(BOMComponentRecord).where(BOMComponentRecord.parent_part_id == part.id)
        ).all()
        if not children:
            return {part.part_number: qty}
        requirements: Dict[str, int] = {}
        for child in children:
            child_requirements = self._leaf_requirements(session, child.component_part.part_number, qty * child.quantity_per)
            for leaf, required in child_requirements.items():
                requirements[leaf] = requirements.get(leaf, 0) + required
        return requirements

    def _bom_tree_node(
        self,
        session: Session,
        part_number: str,
        qty_required: int,
        quantity_per_parent: int,
        location: str,
    ) -> BOMTreeNode:
        part = self._require_part(session, part_number)
        children = session.scalars(
            select(BOMComponentRecord)
            .where(BOMComponentRecord.parent_part_id == part.id)
            .join(BOMComponentRecord.component_part)
            .order_by(PartRecord.part_number)
        ).all()
        child_nodes = [
            self._bom_tree_node(session, child.component_part.part_number, qty_required * child.quantity_per, child.quantity_per, location)
            for child in children
        ]
        return BOMTreeNode(
            part.part_number,
            part.description,
            qty_required,
            quantity_per_parent,
            self.stock_at(part.part_number, location),
            child_nodes,
        )

    def _normalize_part_number(self, part_number: str) -> str:
        return part_number.strip().upper()

    def _normalize_lot_number(self, lot_number: str) -> str:
        lot_number = lot_number.strip().upper()
        if not lot_number:
            raise ValueError("Lot required.")
        return lot_number

    def _part_dto(self, row: PartRecord) -> Part:
        return Part(
            row.part_number,
            row.description,
            row.minimum_quantity,
            row.default_location.name if row.default_location else "Stock",
            row.active,
        )

    def _transaction_dto(self, row: InventoryTransactionRecord) -> Transaction:
        return Transaction(
            row.timestamp,
            row.tx_type,
            row.part.part_number,
            row.quantity_change,
            row.location_from.name if row.location_from else "",
            row.location_to.name if row.location_to else "",
            row.operator,
            row.reference,
            row.notes,
            row.lot.lot_number if row.lot else "",
        )

    def _shipment_dto(self, row: ShipmentRecord) -> Shipment:
        consumed = [
            ComponentConsumption(component.part.part_number, component.quantity, component.location.name, component.lot.lot_number)
            for component in sorted(row.components, key=lambda component: component.id)
        ]
        return Shipment(
            row.shipment_number,
            row.timestamp,
            row.part.part_number,
            row.quantity,
            row.recipient,
            row.carrier,
            row.tracking_number,
            consumed,
        )


STORE = InventoryStore(db_path=None, seed=False)
