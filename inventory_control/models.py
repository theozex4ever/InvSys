from dataclasses import dataclass


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


@dataclass
class Shipment:
    shipment_number: str
    timestamp: str
    part_number: str
    quantity: int
    recipient: str
    carrier: str = ""
    tracking_number: str = ""

