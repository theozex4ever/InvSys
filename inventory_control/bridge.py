"""Narrow desktop use cases. InventoryStore remains the inventory authority."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from threading import RLock
from typing import Any

from inventory_control.models import Part
from inventory_control.store import InventoryStore

logger = logging.getLogger(__name__)


class BridgeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InventoryBridge:
    def __init__(self, store: InventoryStore) -> None:
        # pywebview calls may run on separate threads; serialize this app's requests.
        self._store = store
        self._lock = RLock()

    def _respond(self, operation: Callable[[], Any]) -> dict[str, Any]:
        try:
            with self._lock:
                return {"ok": True, "data": operation()}
        except BridgeError as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}
        except ValueError as error:
            return {"ok": False, "error": {"code": "VALIDATION", "message": str(error)}}
        except Exception:
            logger.exception("Desktop bridge request failed")
            return {
                "ok": False,
                "error": {
                    "code": "INTERNAL",
                    "message": "Something went wrong. Refresh to check current data before trying again.",
                },
            }

    def _part(self, part: Part, low_stock: set[str]) -> dict[str, Any]:
        number = part.part_number
        return {
            **asdict(part),
            "quantity": self._store.total_stock(number),
            "low_stock": number in low_stock,
        }

    def dashboard(self) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            low_parts = self._store.low_stock()
            low_numbers = {part.part_number for part in low_parts}
            return {
                "active_parts": sum(p.active for p in self._store.parts.values()),
                "low_stock": [self._part(p, low_numbers) for p in low_parts],
                "shipment_count": len(self._store.shipments),
                "activity": [asdict(tx) for tx in self._store.transactions[:8]],
            }

        return self._respond(read)

    def _text(self, value: Any, label: str, required: bool = True) -> str:
        if not isinstance(value, str):
            raise BridgeError("VALIDATION", f"{label} must be text.")
        value = value.strip()
        if required and not value:
            raise ValueError(f"{label} required.")
        return value

    def _preferences(self) -> dict[str, str]:
        return {
            "operator": self._store.get_setting("last_operator"),
            "theme": self._store.get_setting("desktop_theme", "light"),
        }

    def preferences(self) -> dict[str, Any]:
        return self._respond(self._preferences)

    def save_operator(self, operator: Any) -> dict[str, Any]:
        def save() -> dict[str, str]:
            self._store.set_setting(
                "last_operator", self._text(operator, "Operator", required=False)
            )
            return self._preferences()

        return self._respond(save)

    def save_theme(self, theme: Any) -> dict[str, Any]:
        def save() -> dict[str, str]:
            if theme not in ("light", "dark"):
                raise ValueError("Choose light or dark mode.")
            self._store.set_setting("desktop_theme", theme)
            return self._preferences()

        return self._respond(save)

    def _request(self, request: Any, allowed: set[str]) -> dict[str, Any]:
        if not isinstance(request, dict) or set(request) - allowed:
            raise ValueError("Invalid request fields.")
        return request

    def search_parts(self, request: Any) -> dict[str, Any]:
        def search() -> list[dict[str, Any]]:
            fields = self._request(
                request, {"query", "status", "low_stock", "sort", "descending"}
            )
            query = self._text(
                fields.get("query", ""), "Search", required=False
            ).casefold()
            status = fields.get("status", "all")
            sort = fields.get("sort", "part_number")
            low = fields.get("low_stock", False)
            descending = fields.get("descending", False)
            if (
                status not in ("all", "active", "inactive")
                or sort
                not in ("part_number", "description", "quantity", "minimum_quantity")
                or type(low) is not bool
                or type(descending) is not bool
            ):
                raise ValueError("Invalid catalog filter or sort.")
            low_numbers = {p.part_number for p in self._store.low_stock()}
            parts = [
                self._part(p, low_numbers)
                for p in self._store.parts.values()
                if query in p.part_number.casefold()
                or query in p.description.casefold()
            ]
            parts = [
                p
                for p in parts
                if (status == "all" or p["active"] == (status == "active"))
                and (not low or p["low_stock"])
            ]
            return sorted(
                parts,
                key=lambda p: (
                    p[sort].casefold() if isinstance(p[sort], str) else p[sort],
                    p["part_number"],
                ),
                reverse=descending,
            )

        return self._respond(search)

    def _detail(self, part_number: Any) -> dict[str, Any]:
        number = self._text(part_number, "Part number").upper()
        part = self._store.parts.get(number)
        if part is None:
            raise BridgeError("NOT_FOUND", "Part not found.")
        return {
            **self._part(part, {p.part_number for p in self._store.low_stock()}),
            "location_balances": self._store.balances.get(number, {}),
            "balances": [asdict(b) for b in self._store.lot_balances(number)],
        }

    def part_detail(self, part_number: Any) -> dict[str, Any]:
        return self._respond(lambda: self._detail(part_number))

    def locations(self) -> dict[str, Any]:
        return self._respond(lambda: self._store.locations)

    def create_part(self, request: Any) -> dict[str, Any]:
        def create() -> dict[str, Any]:
            fields = self._request(
                request, {"part_number", "description", "minimum_quantity", "location"}
            )
            number = self._text(fields.get("part_number"), "Part number").upper()
            description = self._text(fields.get("description"), "Description")
            location = self._text(fields.get("location"), "Location")
            minimum = fields.get("minimum_quantity")
            if type(minimum) is not int or minimum < 0 or minimum > 2**31 - 1:
                raise ValueError(
                    "Minimum quantity must be a whole number between 0 and 2147483647."
                )
            if location not in self._store.locations:
                raise ValueError("Invalid location.")
            if number in self._store.parts:
                raise BridgeError("DUPLICATE", "Part already exists.")
            self._store.add_part(number, description, minimum, location)
            return self._detail(number)

        return self._respond(create)

    def _stock_context(self, part_number: Any) -> dict[str, Any]:
        part = self._detail(part_number)
        number = part["part_number"]
        return {
            "part": part,
            "locations": self._store.locations,
            "has_bom": bool(self._store.bom_children(number)),
            "transactions": [
                asdict(tx)
                for tx in self._store.transactions
                if tx.part_number == number
            ],
            "shipments": [
                asdict(shipment)
                for shipment in self._store.shipments
                if shipment.part_number == number
            ],
        }

    def stock_context(self, part_number: Any) -> dict[str, Any]:
        """Current stock and audit records for reviewing or reconciling a draft."""
        return self._respond(lambda: self._stock_context(part_number))

    def _stock_request(self, request: Any, optional: set[str]) -> dict[str, Any]:
        fields = self._request(
            request,
            {
                "part_number",
                "quantity",
                "location",
                "lot_number",
                "operator",
            }
            | optional,
        )
        values = {
            key: self._text(fields.get(key), label)
            for key, label in (
                ("part_number", "Part number"),
                ("location", "Location"),
                ("lot_number", "Lot"),
                ("operator", "Operator"),
            )
        }
        quantity = fields.get("quantity")
        if type(quantity) is not int or not 0 < quantity <= 2**31 - 1:
            raise ValueError(
                "Quantity must be a whole number between 1 and 2147483647."
            )
        values["quantity"] = quantity
        values["part_number"] = values["part_number"].upper()
        values["lot_number"] = values["lot_number"].upper()
        self._detail(values["part_number"])
        for key in optional:
            values[key] = self._text(
                fields.get(key, ""), key.capitalize(), required=False
            )
        return values

    def receive(self, request: Any) -> dict[str, Any]:
        def receive() -> dict[str, Any]:
            fields = self._stock_request(request, {"reference", "notes"})
            self._store.receive(
                fields["part_number"],
                fields["quantity"],
                fields["location"],
                fields["lot_number"],
                fields["operator"],
                reference=fields["reference"],
                notes=fields["notes"],
            )
            return self._stock_context(fields["part_number"])

        return self._respond(receive)

    def _ship_request(self, request: Any) -> dict[str, Any]:
        fields = self._stock_request(
            request, {"recipient", "carrier", "tracking", "reference"}
        )
        if not fields["recipient"]:
            raise ValueError("Recipient required.")
        if self._store.bom_children(fields["part_number"]):
            raise ValueError(
                "BOM shipping is unavailable here. Use the original application to review allocations."
            )
        return fields

    def preview_ship(self, request: Any) -> dict[str, Any]:
        def preview() -> dict[str, Any]:
            fields = self._ship_request(request)
            context = self._stock_context(fields["part_number"])
            if not context["part"]["active"]:
                raise ValueError("Part is inactive. Reactivate it before shipping.")
            if fields["location"] not in context["locations"]:
                raise ValueError("Invalid location.")
            lots = self._store.lots_for_part(fields["part_number"])
            if fields["lot_number"] not in {lot.lot_number for lot in lots}:
                raise BridgeError("NOT_FOUND", "Lot not found.")
            stock = self._store.stock_at(
                fields["part_number"], fields["location"], fields["lot_number"]
            )
            if fields["quantity"] > stock:
                raise ValueError(
                    f"Not enough stock in selected lot. Available: {stock}, requested: {fields['quantity']}."
                )
            return {
                "request": fields,
                "lot_stock": stock,
                "location_stock": self._store.stock_at(
                    fields["part_number"], fields["location"]
                ),
                "remaining": stock - fields["quantity"],
                "context": context,
            }

        return self._respond(preview)

    def ship(self, request: Any) -> dict[str, Any]:
        def ship() -> dict[str, Any]:
            fields = self._ship_request(request)
            number = self._store.ship(
                fields["part_number"],
                fields["quantity"],
                fields["location"],
                fields["recipient"],
                fields["operator"],
                lot_number=fields["lot_number"],
                carrier=fields["carrier"],
                tracking=fields["tracking"],
                reference=fields["reference"],
            )
            return {
                "shipment_number": number,
                "context": self._stock_context(fields["part_number"]),
            }

        return self._respond(ship)
