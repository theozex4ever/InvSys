import csv
from datetime import datetime
from pathlib import Path
from typing import Callable

from inventory_control.backup import backup_database
from inventory_control.config import BACKUP_DIR, DB_PATH, EXPORT_DIR
from inventory_control.models import CSVPreview, CSVRowIssue, ExportResult, ImportResult
from inventory_control.store import InventoryStore


PARTS_HEADERS = ["part_number", "description", "default_location", "minimum_quantity", "active"]
INVENTORY_HEADERS = ["part_number", "description", "location", "lot_number", "quantity", "minimum_quantity"]
TRANSACTION_HEADERS = [
    "timestamp",
    "tx_type",
    "part_number",
    "lot_number",
    "quantity_change",
    "location_from",
    "location_to",
    "operator",
    "reference",
    "notes",
]
SHIPMENT_HEADERS = [
    "shipment_number",
    "timestamp",
    "part_number",
    "quantity",
    "recipient",
    "carrier",
    "tracking_number",
    "consumed_components",
]
BOM_HEADERS = ["parent_part_number", "component_part_number", "quantity_per"]

IGNORED_PART_COLUMNS = {"barcode", "category", "unit_of_measure", "revision", "notes"}


class ImportExportService:
    def __init__(
        self,
        store: InventoryStore,
        export_dir: Path = EXPORT_DIR,
        backup_dir: Path = BACKUP_DIR,
        db_path: Path = DB_PATH,
    ) -> None:
        self.store = store
        self.export_dir = Path(export_dir)
        self.backup_dir = Path(backup_dir)
        self.db_path = Path(db_path)

    def export_parts_csv(self, path: Path | None = None) -> ExportResult:
        rows = [
            {
                "part_number": part.part_number,
                "description": part.description,
                "default_location": part.location,
                "minimum_quantity": part.minimum_quantity,
                "active": part.active,
            }
            for part in self.store.parts.values()
        ]
        return self._write_csv("parts", PARTS_HEADERS, rows, path)

    def export_inventory_csv(self, path: Path | None = None) -> ExportResult:
        parts = self.store.parts
        rows = []
        for part_number, part in parts.items():
            for balance in self.store.lot_balances(part_number):
                rows.append(
                    {
                        "part_number": balance.part_number,
                        "description": part.description,
                        "location": balance.location,
                        "lot_number": balance.lot_number,
                        "quantity": balance.quantity,
                        "minimum_quantity": part.minimum_quantity,
                    }
                )
        return self._write_csv("inventory", INVENTORY_HEADERS, rows, path)

    def export_transactions_csv(self, path: Path | None = None) -> ExportResult:
        rows = [
            {
                "timestamp": tx.timestamp,
                "tx_type": tx.tx_type,
                "part_number": tx.part_number,
                "lot_number": tx.lot_number,
                "quantity_change": tx.quantity_change,
                "location_from": tx.location_from,
                "location_to": tx.location_to,
                "operator": tx.operator,
                "reference": tx.reference,
                "notes": tx.notes,
            }
            for tx in self.store.transactions
        ]
        return self._write_csv("transactions", TRANSACTION_HEADERS, rows, path)

    def export_shipments_csv(self, path: Path | None = None) -> ExportResult:
        rows = [
            {
                "shipment_number": shipment.shipment_number,
                "timestamp": shipment.timestamp,
                "part_number": shipment.part_number,
                "quantity": shipment.quantity,
                "recipient": shipment.recipient,
                "carrier": shipment.carrier,
                "tracking_number": shipment.tracking_number,
                "consumed_components": ";".join(
                    f"{component.part_number}|{component.lot_number}|{component.location}|{component.quantity}"
                    for component in shipment.consumed_components
                ),
            }
            for shipment in self.store.shipments
        ]
        return self._write_csv("shipments", SHIPMENT_HEADERS, rows, path)

    def export_bom_csv(self, path: Path | None = None) -> ExportResult:
        rows = []
        for parent, components in self.store.bom_components.items():
            for component, quantity_per in components.items():
                rows.append(
                    {
                        "parent_part_number": parent,
                        "component_part_number": component,
                        "quantity_per": quantity_per,
                    }
                )
        return self._write_csv("bom", BOM_HEADERS, rows, path)

    def export_all(self) -> list[ExportResult]:
        timestamp = self._timestamp()
        return [
            self.export_parts_csv(self._export_path("parts", timestamp)),
            self.export_inventory_csv(self._export_path("inventory", timestamp)),
            self.export_transactions_csv(self._export_path("transactions", timestamp)),
            self.export_shipments_csv(self._export_path("shipments", timestamp)),
            self.export_bom_csv(self._export_path("bom", timestamp)),
        ]

    def preview_parts_import_csv(self, path: Path) -> CSVPreview:
        rows, header_errors, warnings = self._read_csv(path, "parts", {"part_number", "description"})
        return self._preview_rows("parts", path, rows, header_errors, warnings, self._validate_part_row)

    def import_parts_csv(self, path: Path, operator: str) -> ImportResult:
        preview = self.preview_parts_import_csv(path)
        self._require_importable(preview)
        rows = [self._part_import_row(row) for _, row in self._read_csv(path, "parts", {"part_number", "description"})[0]]
        backup = self._pre_import_backup()
        self.store.import_parts(rows, notify=True)
        return ImportResult("parts", len(rows), str(backup or ""))

    def preview_inventory_import_csv(self, path: Path) -> CSVPreview:
        required = {"part_number", "location", "lot_number", "quantity"}
        rows, header_errors, warnings = self._read_csv(path, "inventory", required)
        return self._preview_rows("inventory", path, rows, header_errors, warnings, self._validate_inventory_row)

    def import_inventory_csv(self, path: Path, operator: str) -> ImportResult:
        preview = self.preview_inventory_import_csv(path)
        self._require_importable(preview)
        rows = [
            self._inventory_import_row(row)
            for _, row in self._read_csv(path, "inventory", {"part_number", "location", "lot_number", "quantity"})[0]
        ]
        backup = self._pre_import_backup()
        self.store.import_inventory_receipts(rows, operator, notify=True)
        return ImportResult("inventory", len(rows), str(backup or ""))

    def preview_bom_import_csv(self, path: Path) -> CSVPreview:
        rows, header_errors, warnings = self._read_csv(path, "bom", set(BOM_HEADERS))
        preview = self._preview_rows("bom", path, rows, header_errors, warnings, self._validate_bom_row)
        if not preview.errors:
            cycle_errors = self._validate_bom_cycles(rows)
            preview.errors.extend(cycle_errors)
            bad_rows = {error.row_number for error in preview.errors if error.row_number > 1}
            preview.valid_count = max(preview.row_count - len(bad_rows), 0) if not cycle_errors else 0
        return preview

    def import_bom_csv(self, path: Path, operator: str) -> ImportResult:
        preview = self.preview_bom_import_csv(path)
        self._require_importable(preview)
        rows = [self._bom_import_row(row) for _, row in self._read_csv(path, "bom", set(BOM_HEADERS))[0]]
        backup = self._pre_import_backup()
        self.store.import_bom_components(rows, notify=True)
        return ImportResult("bom", len(rows), str(backup or ""))

    def _write_csv(
        self,
        kind: str,
        headers: list[str],
        rows: list[dict[str, object]],
        path: Path | None = None,
    ) -> ExportResult:
        target = Path(path) if path is not None else self._export_path(kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        return ExportResult(kind, str(target), len(rows))

    def _export_path(self, kind: str, timestamp: str | None = None) -> Path:
        return self.export_dir / f"{kind}_{timestamp or self._timestamp()}.csv"

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _read_csv(
        self,
        path: Path,
        kind: str,
        required: set[str],
    ) -> tuple[list[tuple[int, dict[str, str]]], list[CSVRowIssue], list[CSVRowIssue]]:
        target = Path(path)
        errors: list[CSVRowIssue] = []
        warnings: list[CSVRowIssue] = []
        rows: list[tuple[int, dict[str, str]]] = []
        try:
            with target.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    return [], [CSVRowIssue(1, "", "CSV file is empty.")], []
                headers = [header.strip().lower() for header in reader.fieldnames]
                missing = sorted(required - set(headers))
                for column in missing:
                    errors.append(CSVRowIssue(1, column, f"Missing required column: {column}."))
                if kind == "parts":
                    for column in sorted(IGNORED_PART_COLUMNS & set(headers)):
                        warnings.append(
                            CSVRowIssue(
                                1,
                                column,
                                f"Column {column} is accepted for compatibility but is not imported.",
                                "warning",
                            )
                        )
                for row_number, raw in enumerate(reader, start=2):
                    normalized = {}
                    for original, header in zip(reader.fieldnames, headers):
                        normalized[header] = (raw.get(original) or "").strip()
                    rows.append((row_number, normalized))
        except OSError as exc:
            return [], [CSVRowIssue(1, "", f"Could not read CSV: {exc}.")], []
        if not rows and not errors:
            errors.append(CSVRowIssue(1, "", "CSV file has no data rows."))
        return rows, errors, warnings

    def _preview_rows(
        self,
        kind: str,
        path: Path,
        rows: list[tuple[int, dict[str, str]]],
        errors: list[CSVRowIssue],
        warnings: list[CSVRowIssue],
        validator: Callable[[int, dict[str, str], set[tuple[str, ...]]], list[CSVRowIssue]],
    ) -> CSVPreview:
        seen: set[tuple[str, ...]] = set()
        all_errors = list(errors)
        for row_number, row in rows:
            all_errors.extend(validator(row_number, row, seen))
        if errors:
            valid_count = 0
        else:
            bad_rows = {error.row_number for error in all_errors if error.row_number > 1}
            valid_count = max(len(rows) - len(bad_rows), 0)
        return CSVPreview(kind, str(path), len(rows), valid_count, all_errors, warnings)

    def _validate_part_row(
        self,
        row_number: int,
        row: dict[str, str],
        seen: set[tuple[str, ...]],
    ) -> list[CSVRowIssue]:
        errors = []
        part_number = row.get("part_number", "").strip().upper()
        if not part_number:
            errors.append(CSVRowIssue(row_number, "part_number", "Part number required."))
        elif (part_number,) in seen:
            errors.append(CSVRowIssue(row_number, "part_number", "Duplicate part number in CSV."))
        seen.add((part_number,))
        if not row.get("description", "").strip():
            errors.append(CSVRowIssue(row_number, "description", "Description required."))
        minimum = row.get("minimum_quantity", "0") or "0"
        if self._parse_non_negative_int(minimum) is None:
            errors.append(CSVRowIssue(row_number, "minimum_quantity", "Minimum quantity must be a non-negative integer."))
        location = row.get("default_location", "Stock") or "Stock"
        if location not in self.store.locations:
            errors.append(CSVRowIssue(row_number, "default_location", "Default location does not exist."))
        active = row.get("active", "")
        if active and self._parse_bool(active) is None:
            errors.append(CSVRowIssue(row_number, "active", "Active must be true or false."))
        return errors

    def _validate_inventory_row(
        self,
        row_number: int,
        row: dict[str, str],
        seen: set[tuple[str, ...]],
    ) -> list[CSVRowIssue]:
        errors = []
        part_number = row.get("part_number", "").strip().upper()
        location = row.get("location", "").strip()
        lot_number = row.get("lot_number", "").strip().upper()
        key = (part_number, location, lot_number)
        if not part_number:
            errors.append(CSVRowIssue(row_number, "part_number", "Part number required."))
        elif part_number not in self.store.parts:
            errors.append(CSVRowIssue(row_number, "part_number", "Part does not exist."))
        if not location:
            errors.append(CSVRowIssue(row_number, "location", "Location required."))
        elif location not in self.store.locations:
            errors.append(CSVRowIssue(row_number, "location", "Location does not exist."))
        if not lot_number:
            errors.append(CSVRowIssue(row_number, "lot_number", "Lot number required."))
        quantity = self._parse_positive_int(row.get("quantity", ""))
        if quantity is None:
            errors.append(CSVRowIssue(row_number, "quantity", "Quantity must be a positive integer."))
        if key in seen:
            errors.append(CSVRowIssue(row_number, "lot_number", "Duplicate part/location/lot row in CSV."))
        seen.add(key)
        return errors

    def _validate_bom_row(
        self,
        row_number: int,
        row: dict[str, str],
        seen: set[tuple[str, ...]],
    ) -> list[CSVRowIssue]:
        errors = []
        parent = row.get("parent_part_number", "").strip().upper()
        component = row.get("component_part_number", "").strip().upper()
        key = (parent, component)
        if not parent:
            errors.append(CSVRowIssue(row_number, "parent_part_number", "Parent part required."))
        elif parent not in self.store.parts:
            errors.append(CSVRowIssue(row_number, "parent_part_number", "Parent part does not exist."))
        if not component:
            errors.append(CSVRowIssue(row_number, "component_part_number", "Component part required."))
        elif component not in self.store.parts:
            errors.append(CSVRowIssue(row_number, "component_part_number", "Component part does not exist."))
        if parent and component and parent == component:
            errors.append(CSVRowIssue(row_number, "component_part_number", "A part cannot contain itself."))
        if self._parse_positive_int(row.get("quantity_per", "")) is None:
            errors.append(CSVRowIssue(row_number, "quantity_per", "Quantity per must be a positive integer."))
        if key in seen:
            errors.append(CSVRowIssue(row_number, "component_part_number", "Duplicate parent/component row in CSV."))
        seen.add(key)
        return errors

    def _validate_bom_cycles(self, rows: list[tuple[int, dict[str, str]]]) -> list[CSVRowIssue]:
        graph = {parent: set(components) for parent, components in self.store.bom_components.items()}
        for _, row in rows:
            parent = row.get("parent_part_number", "").strip().upper()
            component = row.get("component_part_number", "").strip().upper()
            if parent and component:
                graph.setdefault(parent, set()).add(component)
        errors = []
        for row_number, row in rows:
            parent = row.get("parent_part_number", "").strip().upper()
            component = row.get("component_part_number", "").strip().upper()
            if parent and component and self._path_exists(graph, component, parent):
                errors.append(CSVRowIssue(row_number, "component_part_number", "This component would create a circular BOM."))
        return errors

    def _path_exists(self, graph: dict[str, set[str]], start: str, target: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if start in seen:
            return False
        if start == target:
            return True
        seen.add(start)
        return any(self._path_exists(graph, child, target, seen) for child in graph.get(start, set()))

    def _part_import_row(self, row: dict[str, str]) -> dict[str, object]:
        return {
            "part_number": row.get("part_number", "").strip().upper(),
            "description": row.get("description", "").strip(),
            "minimum_quantity": self._parse_non_negative_int(row.get("minimum_quantity", "0") or "0") or 0,
            "location": row.get("default_location", "Stock") or "Stock",
            "active": self._parse_bool(row.get("active", "")) if row.get("active", "") else True,
        }

    def _inventory_import_row(self, row: dict[str, str]) -> dict[str, object]:
        return {
            "part_number": row.get("part_number", "").strip().upper(),
            "location": row.get("location", "").strip(),
            "lot_number": row.get("lot_number", "").strip().upper(),
            "quantity": self._parse_positive_int(row.get("quantity", "")) or 0,
            "reference": row.get("reference", "").strip() or "CSV import",
            "notes": row.get("notes", "").strip(),
        }

    def _bom_import_row(self, row: dict[str, str]) -> dict[str, object]:
        return {
            "parent_part_number": row.get("parent_part_number", "").strip().upper(),
            "component_part_number": row.get("component_part_number", "").strip().upper(),
            "quantity_per": self._parse_positive_int(row.get("quantity_per", "")) or 0,
        }

    def _parse_positive_int(self, value: str) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _parse_non_negative_int(self, value: str) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    def _parse_bool(self, value: str) -> bool | None:
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
        return None

    def _require_importable(self, preview: CSVPreview) -> None:
        if not preview.can_import:
            raise ValueError("CSV import has validation errors.")

    def _pre_import_backup(self) -> Path | None:
        return backup_database(self.db_path, self.backup_dir, reason="pre-import")
