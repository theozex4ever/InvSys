# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
python inventory_visualizer.py
```

Requires PySide6:

```bash
pip install PySide6
```

Planned additions (not yet set up): `SQLAlchemy`, `pandas`, `pytest`, `ruff`, `pyinstaller`.

## Current Architecture

`inventory_visualizer.py` is now a thin launcher that calls `inventory_control.app.main()`.

**Data layer** — `inventory_control.models` defines the `@dataclass` records (`Part`, `Transaction`, `Shipment`). `inventory_control.store.InventoryStore` is still an in-memory store using plain Python dicts and lists. It holds current balances (`{part_number: {location: qty}}`), transactions, shipments, locations, and the subscriber/notify pattern. There is a single module-level `STORE = InventoryStore()` instance.

**UI layer** — `inventory_control.ui.views` contains six `BaseView` subclasses (`DashboardView`, `PartsView`, `ReceiveView`, `ShipView`, `MoveAdjustView`, `HistoryView`). They are stacked in a `QStackedWidget` inside `inventory_control.ui.main_window.MainWindow`. Views gather input, call `STORE`, and show results with toasts.

**Shared widgets** — `inventory_control.ui.widgets` contains `Card`, `BaseView`, `PartCombo`, `Toast`, `ToastManager`, and `add_field()`. `add_field()` provides persistent labels and required markers so forms do not rely on placeholder memory.

**Styling** — `inventory_control.ui.style.STYLE` is applied in `inventory_control.app`. The current theme is a dark neutral gray UI with clear blue/green/red action colors, visible focus states, larger controls, and reduced decorative noise. Widget roles are controlled via `setObjectName()` (e.g., `"SuccessButton"`, `"DangerButton"`, `"Card"`, `"NavButton"`), and `active="true"` on nav buttons is re-polished with `unpolish/polish` to trigger the active style.

## Planned Architecture (from ROADMAP.md)

The in-memory store is explicitly a placeholder. The intended next step is:

- Replace `InventoryStore` with **SQLite + SQLAlchemy** models (`Part`, `Location`, `InventoryBalance`, `InventoryTransaction`, `Shipment`, `Setting`).
- Extract business logic into **service classes** (`PartService`, `InventoryService`, `ShipmentService`, `BackupService`, `ImportExportService`) — UI views must never write to the database directly.
- Split the single file into a package: `inventory_control/models.py`, `inventory_control/services/`, `inventory_control/ui/`.
- Add startup backups, CSV import/export (with preview before commit), and application logging to `logs/app.log`.

## Key Design Rules

- **Transaction-first inventory**: every balance change must produce a transaction record. The balance table is for fast lookup; the transaction log is the source of truth. Never subtract from a balance without a transaction row.
- **No negative stock**: block shipping/moving/scrapping beyond available quantity; raise `ValueError` with a human-readable message.
- **No hard deletes**: use `active = False` on parts and locations. Never delete transaction or shipment records; instead create reversing transactions.
- **Business logic in services, not views**: views gather input, call a service method, display the result. Services raise `ValueError` for expected validation failures; views catch these and call `self.toast(str(e), "error")`.
- **Move creates two transaction rows**: `MOVE_OUT` from source and `MOVE_IN` to destination — both in one DB transaction so they succeed or fail together.

## Transaction Types

```
RECEIVE, SHIP, MOVE_OUT, MOVE_IN, ADJUST, COUNT_CORRECTION, SCRAP, RETURN
```

Define these as constants, not scattered string literals, once services are introduced.

## Default Locations

```
Receiving, Stock, Shipping Bench, Scrap
```

Created at first launch; do not hard-code location names in business logic — look them up from the store/DB.

## Shipment Number Format

```
SHP-YYYYMMDD-0001
```

Counter resets per day are acceptable for MVP.
