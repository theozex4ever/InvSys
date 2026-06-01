from dataclasses import dataclass, field


@dataclass
class Part:
    part_number: str
    description: str
    minimum_quantity: int = 0
    location: str = "Stock"
    active: bool = True


@dataclass
class Transaction:
    timestamp: str
    tx_type: str
    part_number: str
    quantity_change: int
    location_from: str = ""
    location_to: str = ""
    operator: str = "Operator"
    reference: str = ""
    notes: str = ""
    lot_number: str = ""


@dataclass
class Lot:
    part_number: str
    lot_number: str
    active: bool = True


@dataclass
class LotBalance:
    part_number: str
    lot_number: str
    location: str
    quantity: int


@dataclass
class LotAllocation:
    part_number: str
    lot_number: str
    location: str
    quantity: int


@dataclass
class ComponentConsumption:
    part_number: str
    quantity: int
    location: str
    lot_number: str = ""


@dataclass
class Shipment:
    shipment_number: str
    timestamp: str
    part_number: str
    quantity: int
    recipient: str
    carrier: str = ""
    tracking_number: str = ""
    consumed_components: list[ComponentConsumption] = field(default_factory=list)


@dataclass
class BOMComponent:
    parent_part_number: str
    component_part_number: str
    quantity_per: int


@dataclass
class BOMRequirement:
    part_number: str
    description: str
    quantity_required: int
    stock_available: int
    shortage: int


@dataclass
class BOMTreeNode:
    part_number: str
    description: str
    quantity_required: int
    quantity_per_parent: int
    stock_available: int
    children: list["BOMTreeNode"] = field(default_factory=list)
