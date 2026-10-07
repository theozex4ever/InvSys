"""Stock ledger: the only writer of Stock balances and transaction rows.

Used only inside ``InventoryStore``. Every balance change is posted with its
transaction row in the caller's database transaction. Business rules such as
positive quantities or Location checks stay in the store mutations.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from inventory_control.orm import (
    InventoryBalanceRecord,
    InventoryTransactionRecord,
    LocationRecord,
    LotRecord,
    PartRecord,
)


class InsufficientStock(ValueError):
    """A posting would make a Stock balance negative."""

    def __init__(self, part_number: str, lot_number: str, location: str, available: int, requested: int) -> None:
        super().__init__(f"Not enough stock. Available: {available}, requested: {requested}.")
        self.part_number = part_number
        self.lot_number = lot_number
        self.location = location
        self.available = available
        self.requested = requested


def post(
    session: Session,
    timestamp: str,
    tx_type: str,
    part: PartRecord,
    lot: LotRecord,
    location: LocationRecord,
    delta: int,
    *,
    counterpart: LocationRecord | None = None,
    operator: str,
    reference: str = "",
    notes: str = "",
    shipment_id: int | None = None,
) -> int:
    """Apply ``delta`` to a Stock balance and record it; return the new quantity."""
    balance = session.scalar(
        select(InventoryBalanceRecord).where(
            InventoryBalanceRecord.part_id == part.id,
            InventoryBalanceRecord.location_id == location.id,
            InventoryBalanceRecord.lot_id == lot.id,
        )
    )
    available = balance.quantity if balance is not None else 0
    if available + delta < 0:
        raise InsufficientStock(part.part_number, lot.lot_number, location.name, available, -delta)
    if balance is None:
        balance = InventoryBalanceRecord(
            part_id=part.id,
            location_id=location.id,
            lot_id=lot.id,
            quantity=0,
            updated_at=timestamp,
        )
        session.add(balance)
    balance.quantity = available + delta
    balance.updated_at = timestamp
    if delta < 0:
        location_from, location_to = location, counterpart
    else:
        location_from, location_to = counterpart, location
    _add_row(
        session, timestamp, tx_type, part, lot, delta, location_from, location_to,
        operator, reference, notes, shipment_id,
    )
    session.flush()
    return balance.quantity


def record_phantom(
    session: Session,
    timestamp: str,
    tx_type: str,
    part: PartRecord,
    quantity_change: int,
    location_from: LocationRecord | None,
    *,
    operator: str,
    reference: str = "",
    notes: str = "",
    shipment_id: int | None = None,
) -> None:
    """Record a phantom BOM row that changes no Stock balance."""
    _add_row(
        session, timestamp, tx_type, part, None, quantity_change, location_from, None,
        operator, reference, notes, shipment_id,
    )


def _add_row(
    session: Session,
    timestamp: str,
    tx_type: str,
    part: PartRecord,
    lot: LotRecord | None,
    quantity_change: int,
    location_from: LocationRecord | None,
    location_to: LocationRecord | None,
    operator: str,
    reference: str,
    notes: str,
    shipment_id: int | None,
) -> None:
    session.add(
        InventoryTransactionRecord(
            timestamp=timestamp,
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
