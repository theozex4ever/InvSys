# Inventory Control

A local-first desktop inventory management application built with Python and PySide6. Designed to replace scattered Excel sheets for small operations — parts tracking, stock movement, and shipping records in a single, auditable application.

---

## Overview

This application handles the core inventory workflows that matter most to operators:

- **Receive stock** — add incoming inventory with a full transaction record
- **Ship stock** — reduce inventory and generate a shipment record in one action
- **Nested BOM shipping** — ship an assembly/kit and automatically consume the required component parts
- **BOM trace view** — visualize parent/child structure, nested requirements, component availability, and shortages
- **Move stock** — relocate parts between locations with paired MOVE_OUT / MOVE_IN transactions
- **Adjust stock** — correct physical count discrepancies with a required reason field
- **Parts catalog** — searchable part master with active/inactive state, minimum quantities, and per-location balances
- **Transaction history** — every balance change is logged; nothing is ever deleted or silently overwritten
- **Dashboard** — low-stock alerts, recent activity, and quick-action buttons visible at a glance

The design philosophy is: **make the correct action obvious, make mistakes hard, and make recovery easy.**

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| UI | PySide6 (Qt6) |
| Data (current) | In-memory store (`dict` / `list`) |
| Data (planned) | SQLite + SQLAlchemy ORM |
| Packaging (planned) | PyInstaller |
| Tests | pytest |
| Lint / Format | ruff |

The in-memory store is an intentional placeholder that allows the UI layer to be built and validated before committing to a schema. The SQLAlchemy migration preserves all public service interfaces.

---

## Architecture

```
inventory_control/
├── app.py                  # Entry point — wires store, style, and main window
├── config.py               # Path constants (data/, backups/, exports/, logs/)
├── models.py               # Dataclasses: Part, Transaction, Shipment, BOMComponent, BOMRequirement, BOMTreeNode
├── store.py                # InventoryStore — in-memory state + subscriber pattern
└── ui/
    ├── main_window.py      # MainWindow + QStackedWidget navigation
    ├── views.py            # Task-based views including BOM builder/visualizer
    ├── widgets.py          # Shared components: Card, BaseView, PartCombo, Toast, ToastManager, add_field()
    └── style.py            # Global QSS theme (dark neutral, role-based object names)
```

**Data flow:** Views gather input → call `STORE` methods → display results via toast notifications. No business logic lives inside views.

**Planned service layer:** `PartService`, `InventoryService`, `ShipmentService`, `BackupService`, `ImportExportService` — replacing direct store calls so the UI never touches the database.

---

## Key Design Decisions

**Transaction-first inventory.** Every balance change produces a transaction record. The balance table is for fast lookup; the transaction log is the source of truth. Balances can be recalculated from transactions at any time.

**No negative stock.** Shipping, moving, or scrapping beyond available quantity raises a `ValueError` with a plain-language message. The UI catches it and shows a toast — operators never see a stack trace.

**No hard deletes.** Parts and locations use `active = False`. Transaction and shipment records are never removed; mistakes are corrected with reversing transactions (e.g., `RETURN` corrects an erroneous `SHIP`).

**Business logic in services, not views.** Views are input collectors and result displayers. This boundary keeps the service layer independently testable and the UI layer replaceable.

**Move = two atomic transaction rows.** A stock move creates `MOVE_OUT` from the source and `MOVE_IN` to the destination inside a single database transaction — both succeed or both roll back.

**BOM parents are phantom assemblies in the current MVP.** If a shipped part has a BOM, the shipment is recorded for the parent part, while stock is deducted from the nested leaf components. Intermediate assemblies remain trace nodes unless they have no child BOM of their own.

**BOM shipments are all-or-nothing.** The app explodes the nested BOM first, validates every leaf component at the selected location, and blocks the shipment if any component is short. No partial deductions or shipment records are created on failure.

---

## Transaction Types

```
RECEIVE       Inbound stock
SHIP          Outbound — creates a linked shipment record
SHIP_BOM      Outbound parent shipment fulfilled by BOM component consumption
BOM_CONSUME   Leaf component deducted for a linked BOM shipment
MOVE_OUT      Source side of a location transfer
MOVE_IN       Destination side of a location transfer
ADJUST        Manual balance correction with required reason
COUNT_CORRECTION   Physical count reconciliation
SCRAP         Write-off with required reason
RETURN        Reversal of an erroneous outbound transaction
```

---

## Running the App

```bash
pip install PySide6
python inventory_visualizer.py
```

No database setup required — default locations (`Receiving`, `Stock`, `Shipping Bench`, `Scrap`) are created on first launch.

---

## Planned Database Schema

Once the SQLAlchemy layer is introduced, the core tables will be:

| Table | Purpose |
|---|---|
| `parts` | Part master — number, description, category, UoM, min qty, active |
| `locations` | Named stock locations — active flag, no hard deletes |
| `inventory_balances` | Current qty per part/location — fast lookup only |
| `inventory_transactions` | Immutable audit log — every balance change |
| `shipments` | Outbound shipment records — number, recipient, carrier, tracking |
| `bom_components` | Parent/component links — quantity per parent, recursive BOM structure |
| `shipment_components` | Snapshot of component consumption for BOM shipment traceability |
| `settings` | Key/value app preferences — last operator, backup count |

Shipment number format: `SHP-YYYYMMDD-0001` (counter resets per day).

---

## Planned MVP Feature Scope

**Must-have (in progress)**
- SQLite + SQLAlchemy persistence
- Persistent nested BOM tables and BOM shipment component snapshots
- Service layer with full test coverage
- CSV export (parts, inventory, transactions, shipments)
- CSV export/import for BOM definitions
- CSV import with row-level preview and validation
- Automatic startup backups + manual backup button
- Application log file (`logs/app.log`)

**Should-have**
- Barcode field on parts; barcode-compatible search input
- CSV import preview screen before commit
- Recent parts quick-select

**Not in MVP**
- Purchase orders, sales orders, supplier/customer databases
- Role-based permissions, password login
- Cloud sync, carrier API integrations, label printing
- Serial / lot / expiry tracking

---

## Development Roadmap

| Phase | Goal | Status |
|---|---|---|
| 0 | App skeleton + navigation | Done |
| 1 | Database + SQLAlchemy models | Planned |
| 2 | Parts management + PartService | Planned |
| 3 | Inventory core + service tests | Planned |
| 3B | Nested BOM core + shipment explosion traceability | Done (in-memory) |
| 4 | Receive / Ship UI | Done (in-memory) |
| 5 | Move / Adjust UI | Done (in-memory) |
| 6 | Dashboard + History | Done (in-memory) |
| 7 | CSV import/export + backup | Planned |
| 8 | MVP hardening + PyInstaller | Planned |

---

## Restoring a Backup

```
1. Close the app.
2. Open the backups/ folder.
3. Copy the desired backup file.
4. Rename it to inventory.db.
5. Replace data/inventory.db with it.
6. Restart the app.
```

---

## License

MIT
