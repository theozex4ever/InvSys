from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PartRecord(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_number: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    minimum_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    default_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    default_location: Mapped["LocationRecord | None"] = relationship()


class LocationRecord(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class LotRecord(Base):
    __tablename__ = "lots"
    __table_args__ = (UniqueConstraint("part_id", "lot_number", name="uq_lots_part_lot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    lot_number: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    part: Mapped[PartRecord] = relationship()


class InventoryBalanceRecord(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("part_id", "location_id", "lot_id", name="uq_inventory_balances_part_location_lot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False, index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    part: Mapped[PartRecord] = relationship()
    location: Mapped[LocationRecord] = relationship()
    lot: Mapped[LotRecord] = relationship()


class InventoryTransactionRecord(Base):
    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tx_type: Mapped[str] = mapped_column(String, nullable=False)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), index=True)
    quantity_change: Mapped[int] = mapped_column(Integer, nullable=False)
    location_from_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    location_to_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    operator: Mapped[str] = mapped_column(String, nullable=False)
    reference: Mapped[str] = mapped_column(String, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"), index=True)

    part: Mapped[PartRecord] = relationship()
    lot: Mapped[LotRecord | None] = relationship()
    location_from: Mapped[LocationRecord | None] = relationship(foreign_keys=[location_from_id])
    location_to: Mapped[LocationRecord | None] = relationship(foreign_keys=[location_to_id])


class ShipmentRecord(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_number: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    timestamp: Mapped[str] = mapped_column(String, nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient: Mapped[str] = mapped_column(String, nullable=False)
    carrier: Mapped[str] = mapped_column(String, nullable=False, default="")
    tracking_number: Mapped[str] = mapped_column(String, nullable=False, default="")
    reference: Mapped[str] = mapped_column(String, nullable=False, default="")

    part: Mapped[PartRecord] = relationship()
    components: Mapped[list["ShipmentComponentRecord"]] = relationship(back_populates="shipment")


class ShipmentComponentRecord(Base):
    __tablename__ = "shipment_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shipment: Mapped[ShipmentRecord] = relationship(back_populates="components")
    part: Mapped[PartRecord] = relationship()
    lot: Mapped[LotRecord] = relationship()
    location: Mapped[LocationRecord] = relationship()


class BOMComponentRecord(Base):
    __tablename__ = "bom_components"
    __table_args__ = (
        UniqueConstraint("parent_part_id", "component_part_id", name="uq_bom_components_parent_component"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    component_part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    quantity_per: Mapped[int] = mapped_column(Integer, nullable=False)

    parent_part: Mapped[PartRecord] = relationship(foreign_keys=[parent_part_id])
    component_part: Mapped[PartRecord] = relationship(foreign_keys=[component_part_id])


class SettingRecord(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
