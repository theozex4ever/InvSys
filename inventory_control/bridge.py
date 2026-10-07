"""Narrow desktop use cases. InventoryStore remains the inventory authority."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from secrets import token_urlsafe
from threading import RLock
from typing import Any

from inventory_control.models import BOMShipmentPlan
from inventory_control.store import InventoryStore, ShipmentReviewNotFound

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
        self._bom_reviews: dict[str, tuple[dict[str, Any], BOMShipmentPlan]] = {}

    def _respond(self, operation: Callable[[], Any]) -> dict[str, Any]:
        try:
            with self._lock:
                return {"ok": True, "data": operation()}
        except BridgeError as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}
        except ShipmentReviewNotFound as error:
            return {"ok": False, "error": {"code": "NOT_FOUND", "message": str(error)}}
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

    def dashboard(self) -> dict[str, Any]:
        return self._respond(self._store.dashboard)

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
            fields = self._request(request, {"query", "status", "low_stock", "sort", "descending"})
            query = self._text(fields.get("query", ""), "Search", required=False).casefold()
            status = fields.get("status", "all")
            sort = fields.get("sort", "part_number")
            low = fields.get("low_stock", False)
            descending = fields.get("descending", False)
            if (
                status not in ("all", "active", "inactive")
                or sort not in ("part_number", "description", "quantity", "minimum_quantity")
                or type(low) is not bool
                or type(descending) is not bool
            ):
                raise ValueError("Invalid catalog filter or sort.")
            return self._store.search_parts(
                query, status=status, low_stock=low, sort=sort, descending=descending
            )

        return self._respond(search)

    def _detail(self, part_number: Any) -> dict[str, Any]:
        number = self._text(part_number, "Part number").upper()
        part = self._store.part_detail(number)
        if part is None:
            raise BridgeError("NOT_FOUND", "Part not found.")
        return part

    def part_detail(self, part_number: Any) -> dict[str, Any]:
        return self._respond(lambda: self._detail(part_number))

    def locations(self) -> dict[str, Any]:
        return self._respond(lambda: self._store.locations)

    def history(self, request: Any) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            fields = self._request(request, {"query", "tx_type", "page"})
            query = self._text(fields.get("query", ""), "Search", required=False)
            tx_type = self._text(fields.get("tx_type", ""), "Transaction type", required=False)
            page = fields.get("page", 0)
            if type(page) is not int or not 0 <= page <= 2**31 - 1:
                raise ValueError("History page must be a nonnegative whole number.")
            return self._store.search_history(query, tx_type, page)

        return self._respond(read)

    def _shipment_detail(self, shipment_number: Any) -> dict[str, Any]:
        number = self._text(shipment_number, "Shipment number").upper()
        detail = self._store.shipment_detail(number)
        if detail is None:
            raise BridgeError("NOT_FOUND", "Shipment not found.")
        return detail

    def shipment_detail(self, shipment_number: Any) -> dict[str, Any]:
        return self._respond(lambda: self._shipment_detail(shipment_number))

    def history_detail(self, transaction_id: Any) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            if type(transaction_id) is not int or transaction_id < 1:
                raise ValueError("Transaction ID must be a positive whole number.")
            transaction = next(
                iter(self._store.history_records(transaction_id=transaction_id)),
                None,
            )
            if transaction is None:
                raise BridgeError("NOT_FOUND", "History record not found.")
            return {
                "transaction": transaction,
                "shipment": self._shipment_detail(transaction["shipment_number"])
                if transaction["shipment_number"]
                else None,
            }

        return self._respond(read)

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
        number = self._text(part_number, "Part number").upper()
        context = self._store.stock_context(number)
        if context is None:
            raise BridgeError("NOT_FOUND", "Part not found.")
        return context

    def stock_context(self, part_number: Any) -> dict[str, Any]:
        """Current stock and audit records for reviewing or reconciling a draft."""
        return self._respond(lambda: self._stock_context(part_number))

    def _stock_request(
        self,
        request: Any,
        optional: set[str],
        require_lot: bool = True,
        *,
        check_inventory: bool = True,
    ) -> dict[str, Any]:
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
                *([("lot_number", "Lot")] if require_lot else []),
                ("operator", "Operator"),
            )
        }
        quantity = fields.get("quantity")
        if type(quantity) is not int or not 0 < quantity <= 2**31 - 1:
            raise ValueError("Quantity must be a whole number between 1 and 2147483647.")
        values["quantity"] = quantity
        values["part_number"] = values["part_number"].upper()
        if require_lot:
            values["lot_number"] = values["lot_number"].upper()
        if check_inventory:
            self._detail(values["part_number"])
        for key in optional:
            values[key] = self._text(fields.get(key, ""), key.capitalize(), required=False)
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

    def _ship_request(self, request: Any, *, check_inventory: bool = True) -> dict[str, Any]:
        fields = self._stock_request(
            request,
            {"recipient", "carrier", "tracking", "reference"},
            check_inventory=check_inventory,
        )
        if not fields["recipient"]:
            raise ValueError("Recipient required.")
        if check_inventory and self._store.bom_children(fields["part_number"]):
            raise ValueError(
                "BOM shipping is unavailable here. Use the original application to review allocations."
            )
        return fields

    def preview_ship(self, request: Any) -> dict[str, Any]:
        def preview() -> dict[str, Any]:
            fields = self._ship_request(request, check_inventory=False)
            review = self._store.review_standard_shipment(
                fields["part_number"],
                fields["quantity"],
                fields["location"],
                fields["lot_number"],
            )
            return {"request": fields, **asdict(review)}

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

    def _bom_request(self, request: Any, *, check_inventory: bool = True) -> dict[str, Any]:
        fields = self._request(
            request,
            {
                "part_number",
                "quantity",
                "location",
                "operator",
                "recipient",
                "carrier",
                "tracking",
                "reference",
            },
        )
        # BOM parents are phantom assemblies; there is no parent lot selection.
        values = self._stock_request(
            fields,
            {"recipient", "carrier", "tracking", "reference"},
            require_lot=False,
            check_inventory=check_inventory,
        )
        if not values["recipient"]:
            raise ValueError("Recipient required.")
        if check_inventory and not self._store.bom_children(values["part_number"]):
            raise ValueError("This part has no BOM. Review a standard shipment instead.")
        return values

    def preview_bom_ship(self, request: Any) -> dict[str, Any]:
        def preview() -> dict[str, Any]:
            fields = self._bom_request(request, check_inventory=False)
            review = self._store.review_bom_shipment(
                fields["part_number"], fields["quantity"], fields["location"]
            )
            plan = review.plan
            review_id = ""
            if plan.ready:
                review_id = token_urlsafe(24)
                # Reviews are session-local capabilities, bounded to avoid unbounded reads.
                if len(self._bom_reviews) >= 128:
                    del self._bom_reviews[next(iter(self._bom_reviews))]
                self._bom_reviews[review_id] = (fields, plan)
            serialized = asdict(plan)
            serialized["requirements"] = list(serialized["requirements"])
            serialized["lines"] = list(serialized["lines"])
            return {
                "request": dict(fields),
                "plan": serialized,
                "review_id": review_id,
                "buildable": review.buildable,
                "context": review.context,
            }

        return self._respond(preview)

    def ship_bom(self, request: Any) -> dict[str, Any]:
        def ship() -> dict[str, Any]:
            if not isinstance(request, dict):
                raise ValueError("Invalid request fields.")
            fields = self._bom_request(
                {key: value for key, value in request.items() if key != "review_id"}
            )
            review_id = self._text(request.get("review_id", ""), "BOM review")
            review = self._bom_reviews.get(review_id)
            if review is None or review[0] != fields:
                raise ValueError(
                    "Review this BOM shipment before confirming. The review is missing, expired, or does not match the draft."
                )
            # A used/rejected review cannot authorize another submission.
            del self._bom_reviews[review_id]
            try:
                number = self._store.ship(
                    fields["part_number"],
                    fields["quantity"],
                    fields["location"],
                    fields["recipient"],
                    fields["operator"],
                    carrier=fields["carrier"],
                    tracking=fields["tracking"],
                    reference=fields["reference"],
                    expected_bom_plan=review[1],
                )
            except ValueError as error:
                if str(error).startswith("BOM lot allocation changed"):
                    raise BridgeError("PLAN_CHANGED", str(error)) from error
                raise
            return {
                "shipment_number": number,
                "context": self._stock_context(fields["part_number"]),
            }

        return self._respond(ship)
