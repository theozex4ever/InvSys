# ROADMAP.md — Inventory Control MVP

## TL;DR

Build a **simple local desktop inventory control application** using **Python + SQLite + PySide6 + SQLAlchemy**. This is not a full production ERP yet. The MVP should replace scattered Excel sheets for **parts, nested BOMs, inventory quantities, stock movement, component usage, and basic shipping records** while staying intuitive for non-technical operators.

The app should focus on five core workflows:

1. **Find or create a part**
2. **Define and visualize a nested BOM**
3. **Receive stock**
4. **Ship stock or a BOM parent**
5. **Move or correct stock**

Core principles:

- Keep it local-first and offline-capable.
- Avoid overengineering.
- Use a simple SQLite database file.
- Record every inventory change as a transaction.
- Treat BOM shipment consumption as traceable inventory transactions linked to the shipment.
- Make BOM structure and shortages visible before shipping.
- Make the UI task-based, not database-table-based.
- Prioritize low-friction, ADHD-friendly operation.
- Make mistakes hard, visible, and recoverable.
- Do not delete history; correct mistakes with reversing/correction transactions.
- Add backups from day one.

The MVP must include:

- Parts database
- Locations
- Current inventory balances by part/location
- Inventory transaction history
- Lot tracking
- Nested BOM definitions
- Recursive BOM visualization
- BOM shipment explosion and component consumption
- BOM component shortage checks
- Receive stock
- Ship stock
- Move stock
- Adjust/correct stock count
- Simple shipment records
- Search
- Low-stock alerts
- CSV export
- Basic CSV import
- Automatic local backups
- Operator name capture

Do **not** include in the MVP unless explicitly required:

- Accounting
- Purchase orders
- Sales orders
- Customer CRM
- Supplier management
- Carrier API integrations
- Label printing
- User roles/permissions
- Cloud sync
- Complex reporting
- Multi-company support

---

# 1. Project Purpose

## 1.1 Problem Being Solved

The current process relies on multiple Excel sheets. This creates common issues:

- Duplicate data entry
- Inconsistent part names or part numbers
- Hard-to-trace stock changes
- No reliable audit history
- Manual shipping records
- Risk of stale spreadsheet versions
- Operators needing to remember too much context

The MVP should provide one local application where users can:

- Look up parts quickly
- Define which components are used by assemblies, kits, and shipped products
- Visualize nested BOM relationships and component shortages
- See available stock
- Receive new inventory
- Ship inventory and automatically consume BOM components
- Move stock between locations
- Correct stock counts
- Review recent activity
- Export data when needed

## 1.2 MVP Definition

The MVP is a **local inventory control app**, not a full ERP.

A successful MVP is one that allows a junior operator to complete the most common inventory tasks without opening Excel.

The MVP is complete when the following can be done end-to-end:

```text
Create part
→ Define nested BOM
→ Receive stock
→ View updated stock
→ Ship BOM parent
→ View shipment record
→ View component consumption trace
→ View transaction history
→ Export current inventory
→ Recover from backup if needed
```

---

# 2. Guiding Product Principles

## 2.1 Keep It Simple

Every feature should answer one of these questions:

- Does this help someone find a part?
- Does this help keep inventory accurate?
- Does this help track movement?
- Does this help ship parts?
- Does this prevent or recover from mistakes?

If not, postpone it.

## 2.2 Task-Based UI, Not Table-Based UI

Users should not feel like they are editing database tables.

Use screens named after tasks:

- Dashboard
- Parts
- BOM
- Receive Stock
- Ship Stock
- Move / Adjust
- History
- Settings

Avoid making the main workflow feel like raw spreadsheets.

## 2.3 Transaction-First Inventory

Every inventory change must create a transaction record.

Examples:

```text
RECEIVE +10
SHIP -3
MOVE -5 from Rack A, +5 to Rack B
ADJUST -2 after count correction
RETURN +1
SCRAP -1
```

The current inventory balance is updated for fast lookup, but the transaction log is the source of traceability.

## 2.4 No Silent Changes

The app must clearly confirm when something happened.

Good:

```text
Done — 8 units received.
Current stock in Rack A: 23.
```

Bad:

```text
Saved.
```

## 2.5 Preserve History

Do not delete inventory transactions.

If a mistake is made, create a correction transaction.

Example:

```text
Original mistake: SHIP -5
Correction: RETURN +5, reference: Correction for transaction #104
```

---

# 3. ADHD-Friendly and Low-Friction UX Requirements

This section is important. The app should be easy for operators who may be distracted, tired, interrupted, or unfamiliar with technical systems.

## 3.1 One Main Action Per Screen

Each screen should have one obvious job.

Examples:

- Receive Stock screen: primary action is `Receive Stock`
- Ship Stock screen: primary action is `Ship Stock`
- Move / Adjust screen: primary action changes depending on selected mode

Avoid screens with many equally prominent buttons.

## 3.2 Strong Visual Hierarchy

Each screen should include:

- Clear page title
- Short helper text
- Large primary action button
- Required fields visibly marked
- Optional fields grouped separately
- Clear success/error messages

Example layout:

```text
Receive Stock
Add inventory for an existing part.

[Part search]
[Quantity]
[Location]
[Reference]

Advanced details ▼
[Notes]

[Receive Stock]
```

## 3.3 Progressive Disclosure

Keep basic forms short.

Required fields should appear first.

Optional or advanced fields should be collapsed or visually separated.

Example required fields for receiving:

```text
Part
Quantity
Location
Operator
```

Optional fields:

```text
Reference
Notes
```

## 3.4 Reduce Typing

Implement these wherever practical:

- Autocomplete part search
- Dropdown location selection
- Remember last operator name
- Remember last used location
- Recent parts list
- Duplicate previous entry action
- Barcode scanner-compatible search input

A USB barcode scanner usually behaves like a keyboard, so the app does not need special barcode hardware support for the MVP. It only needs a focused input field that accepts scanned text.

## 3.5 Helpful Error Messages

Do not show raw database or Python errors to users.

Bad:

```text
sqlite3.IntegrityError: UNIQUE constraint failed
```

Good:

```text
A part with this part number already exists.
Open the existing part instead?
```

## 3.6 Clear Guardrails

The app should prevent obvious mistakes.

Examples:

- Quantity must be greater than zero.
- Cannot ship more than available stock.
- Cannot delete a part with transaction history.
- Adjustment reason is required.
- Warn when a shipment leaves stock below minimum.

## 3.7 Recent Activity Feed

The dashboard should show recent actions, such as:

- Recently received stock
- Recently shipped stock
- Recent adjustments
- Low-stock items

This reduces reliance on memory.

## 3.8 No Hidden Filters

If a filter is applied, show it clearly.

Example:

```text
Showing: Low stock only     [Clear filter]
```

---

# 4. Technology Stack

## 4.1 Recommended Stack

Use:

```text
Python 3.12+
SQLite
SQLAlchemy
PySide6
```

Optional but useful:

```text
pandas        # CSV import/export helpers
pytest        # automated tests
ruff          # linting/formatting
pyinstaller   # future packaging
```

## 4.2 Why Desktop Instead of Web for MVP

Use PySide6 desktop UI for the MVP because:

- It works offline.
- It avoids local server setup.
- It feels like a normal application.
- It is easier for non-technical operators.
- It avoids deployment concerns too early.

Avoid Flask/FastAPI for now unless multi-user browser access becomes a real requirement.

## 4.3 Local File Layout for Operators

Eventually package the app into a simple folder structure:

```text
InventoryControl/
├── InventoryControl.exe
├── data/
│   └── inventory.db
├── backups/
│   ├── inventory_2026-05-21_0900.db
│   └── inventory_2026-05-21_1300.db
├── exports/
└── logs/
```

During development, use a project layout like this:

```text
inventory_control/
├── README.md
├── ROADMAP.md
├── requirements.txt
├── app.py
├── inventory_control/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── part_service.py
│   │   ├── inventory_service.py
│   │   ├── shipment_service.py
│   │   ├── backup_service.py
│   │   └── import_export_service.py
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py
│   │   ├── dashboard_view.py
│   │   ├── parts_view.py
│   │   ├── receive_view.py
│   │   ├── ship_view.py
│   │   ├── move_adjust_view.py
│   │   ├── history_view.py
│   │   └── settings_view.py
│   └── utils/
│       ├── __init__.py
│       ├── validation.py
│       └── formatting.py
├── tests/
│   ├── test_inventory_service.py
│   ├── test_part_service.py
│   └── test_shipment_service.py
└── sample_data/
    ├── parts_sample.csv
    └── inventory_sample.csv
```

---

# 5. MVP Feature Scope

## 5.1 Must-Have Features

The MVP must include:

- Add/edit parts
- Mark parts active/inactive
- Search parts
- Add/edit nested BOM component links
- Detect and block circular BOMs
- Visualize BOM trees and flattened component requirements
- Consume BOM leaf components automatically when shipping a BOM parent
- Link BOM consumption transactions to the shipment record
- Add/edit simple locations
- View current inventory by part and location
- Receive stock
- Ship stock
- Move stock between locations
- Adjust/correct stock count
- Record every inventory transaction
- Record basic shipment details
- Prevent negative stock by default
- Low-stock alerts
- Recent activity feed
- CSV export
- CSV import for initial setup
- Automatic database backup
- Manual backup button
- Operator name capture

## 5.2 Should-Have Features

Implement if time allows:

- Barcode value field on parts
- Barcode-compatible search field
- Recent part quick selection
- Duplicate previous receive/ship action
- CSV import preview screen
- Open backup folder button
- Open export folder button
- Basic application log file

## 5.3 Not in MVP

Do not build these yet:

- Full purchase orders
- Full sales orders
- Supplier database
- Customer database
- Accounting
- Inventory valuation
- Label printing
- Carrier integrations
- Role-based permissions
- Password login
- Multi-user locking
- Cloud sync
- Serial number tracking
- Lot/batch tracking
- Expiry tracking
- Complex dashboards
- REST API

---

# 6. Database Design

## 6.1 Core Tables

The MVP database should contain these tables:

```text
parts
locations
bom_components
inventory_balances
inventory_transactions
shipments
shipment_components
settings
```

Optional later:

```text
users
suppliers
customers
purchase_orders
sales_orders
attachments
```

## 6.2 SQLAlchemy Models

Use SQLAlchemy ORM models to avoid raw SQL scattered throughout the app.

Recommended models:

- `Part`
- `Location`
- `InventoryBalance`
- `InventoryTransaction`
- `Shipment`
- `BOMComponent`
- `ShipmentComponent`
- `Setting`

## 6.3 Table: parts

Purpose: Stores master part data.

Fields:

```text
id                  integer primary key
part_number         text, required, unique
barcode             text, optional, unique if provided
description         text, required
category            text, optional
unit_of_measure     text, default "ea"
default_location_id integer, optional FK to locations.id
minimum_quantity    integer, default 0
revision            text, optional
active              boolean, default true
notes               text, optional
created_at          datetime
updated_at          datetime
```

Rules:

- `part_number` is required and unique.
- `description` is required.
- `minimum_quantity` cannot be negative.
- Parts with transaction history should not be hard-deleted.
- Use `active = false` instead of deleting old parts.

## 6.3A Table: bom_components

Purpose: Stores parent/component links for nested bill-of-material definitions.

Fields:

```text
id                    integer primary key
parent_part_id        integer, required FK to parts.id
component_part_id     integer, required FK to parts.id
quantity_per_parent   integer, required
notes                 text, optional
created_at            datetime
updated_at            datetime
```

Rules:

- A parent part can have many component parts.
- A component can itself be a parent of another BOM.
- `quantity_per_parent` must be greater than zero.
- Circular BOMs are blocked.
- Parent/component duplicates should update quantity rather than creating duplicate rows.
- In the current MVP model, BOM parents are treated as phantom assemblies for shipping: shipping the parent creates a shipment for the parent and deducts nested leaf components.

## 6.4 Table: locations

Purpose: Stores simple inventory locations.

Fields:

```text
id              integer primary key
name            text, required, unique
description     text, optional
active          boolean, default true
created_at      datetime
updated_at      datetime
```

Recommended default locations created at first launch:

```text
Receiving
Stock
Shipping Bench
Scrap
```

Rules:

- Location names are unique.
- Locations with history should not be hard-deleted.
- Use `active = false` instead.

## 6.5 Table: inventory_balances

Purpose: Stores current quantity by part and location for fast lookup.

Fields:

```text
id              integer primary key
part_id         integer, required FK to parts.id
location_id     integer, required FK to locations.id
quantity        integer, required, default 0
updated_at      datetime
```

Rules:

- Unique combination: `part_id + location_id`
- Quantity cannot be negative in MVP.
- Quantity should only be changed through inventory service methods.
- UI code must never directly modify this table.

## 6.6 Table: inventory_transactions

Purpose: Audit trail of every inventory movement.

Fields:

```text
id                  integer primary key
part_id             integer, required FK to parts.id
transaction_type    text, required
quantity_change     integer, required
from_location_id    integer, optional FK to locations.id
to_location_id      integer, optional FK to locations.id
reference           text, optional
operator_name       text, required
notes               text, optional
related_shipment_id integer, optional FK to shipments.id
created_at          datetime
```

Allowed transaction types:

```text
RECEIVE
SHIP
SHIP_BOM
BOM_CONSUME
MOVE_OUT
MOVE_IN
ADJUST
COUNT_CORRECTION
SCRAP
RETURN
```

Rules:

- Receive transactions use positive quantity.
- Ship, scrap, and negative adjustments use negative quantity.
- `SHIP_BOM` records the parent part shipped.
- `BOM_CONSUME` records each leaf component quantity deducted for a linked shipment.
- Moves should create two transaction rows:
  - `MOVE_OUT` from the source location
  - `MOVE_IN` to the destination location
- Corrections should be new transactions, not edits to old transactions.
- Do not hard-delete transaction records.

## 6.7 Table: shipments

Purpose: Stores simple shipping records.

Fields:

```text
id              integer primary key
shipment_number text, required, unique
part_id         integer, required FK to parts.id
quantity        integer, required
location_id     integer, required FK to locations.id
recipient       text, required
carrier         text, optional
tracking_number text, optional
operator_name   text, required
reference       text, optional
notes           text, optional
created_at      datetime
```

Rules:

- Shipping stock must create a shipment record.
- Shipping stock must create an inventory transaction.
- Shipping stock must reduce inventory balance.
- Cannot ship more than available stock.
- If the shipped part has a BOM, shipping must validate and consume required leaf components instead of silently relying on a spreadsheet.

For MVP, one shipment record can represent one part. Do not build multi-line shipments unless needed immediately.

## 6.8A Table: shipment_components

Purpose: Stores the exact BOM component consumption snapshot for a shipment.

Fields:

```text
id              integer primary key
shipment_id     integer, required FK to shipments.id
part_id         integer, required FK to parts.id
quantity        integer, required
location_id     integer, required FK to locations.id
created_at      datetime
```

Rules:

- Created only for BOM shipments.
- Stores leaf component quantities actually deducted.
- Must match linked `BOM_CONSUME` inventory transactions.
- Preserves traceability even if the BOM definition changes later.

## 6.8 Table: settings

Purpose: Stores simple local application preferences.

Fields:

```text
key         text primary key
value       text
updated_at  datetime
```

Example settings:

```text
last_operator_name
last_location_id
backup_keep_count
app_version
```

---

# 7. Business Logic Rules

All business logic should live in service classes, not directly in the UI.

Recommended service classes:

```text
PartService
InventoryService
ShipmentService
BackupService
ImportExportService
SettingsService
```

## 7.1 PartService Responsibilities

Methods to implement:

```text
create_part(...)
update_part(...)
deactivate_part(part_id)
search_parts(query, include_inactive=False)
get_part(part_id)
get_part_by_part_number(part_number)
get_part_by_barcode(barcode)
```

Validation:

- Part number required.
- Description required.
- Part number must be unique.
- Barcode must be unique if provided.
- Minimum quantity cannot be negative.

## 7.2 InventoryService Responsibilities

Methods to implement:

```text
get_balance(part_id, location_id)
get_total_balance(part_id)
receive_stock(part_id, quantity, location_id, operator_name, reference=None, notes=None)
ship_stock(part_id, quantity, location_id, operator_name, recipient, carrier=None, tracking_number=None, reference=None, notes=None)
move_stock(part_id, quantity, from_location_id, to_location_id, operator_name, reference=None, notes=None)
adjust_stock(part_id, location_id, new_count, operator_name, reason, notes=None)
scrap_stock(part_id, quantity, location_id, operator_name, reason, notes=None)
return_stock(part_id, quantity, location_id, operator_name, reference=None, notes=None)
get_low_stock_parts()
get_recent_transactions(limit=25)
```

Rules:

- Quantity inputs must be positive integers.
- Operator name is required.
- Do not allow negative inventory by default.
- Adjustment reason is required.
- Shipping should call `ShipmentService` or coordinate shipment creation in a single database transaction.
- If the shipped part has a BOM, shipping should explode nested requirements, validate component stock, create shipment component snapshots, and create linked `BOM_CONSUME` transactions.
- Database commit should happen only after all related updates succeed.

## 7.3 BOMService Responsibilities

Methods to implement:

```text
add_component(parent_part_id, component_part_id, quantity_per_parent, notes=None)
update_component(parent_part_id, component_part_id, quantity_per_parent, notes=None)
remove_component(parent_part_id, component_part_id)
get_bom_tree(parent_part_id, quantity=1, location_id=None)
get_flat_requirements(parent_part_id, quantity=1, location_id=None)
validate_no_cycle(parent_part_id, component_part_id)
get_can_ship_quantity(parent_part_id, location_id)
```

Rules:

- Quantity per parent must be greater than zero.
- A part cannot contain itself.
- Circular BOMs are blocked.
- Nested BOM visualization must show intermediate assemblies and leaf component shortages.
- Flattened requirements must aggregate duplicate leaf components used through different branches.

## 7.4 ShipmentService Responsibilities

Methods to implement:

```text
create_shipment(...)
generate_shipment_number()
search_shipments(query=None, start_date=None, end_date=None)
get_recent_shipments(limit=25)
```

Shipment number format:

```text
SHP-YYYYMMDD-0001
```

Example:

```text
SHP-20260521-0001
```

Rules:

- Shipment number must be unique.
- Recipient is required.
- Quantity must be positive.
- Shipment creation should happen as part of the shipping workflow.

## 7.5 BackupService Responsibilities

Methods to implement:

```text
create_backup(reason="manual")
create_startup_backup()
create_pre_import_backup()
cleanup_old_backups(keep_count=20)
get_backup_folder_path()
```

Backup naming convention:

```text
inventory_YYYYMMDD_HHMMSS_REASON.db
```

Examples:

```text
inventory_20260521_090000_startup.db
inventory_20260521_103012_pre_import.db
inventory_20260521_144500_manual.db
```

Rules:

- Create a backup on app startup.
- Create a backup before CSV import.
- Keep the latest 20 backups by default.
- Never overwrite an existing backup file.

## 7.6 ImportExportService Responsibilities

Methods to implement:

```text
export_parts_csv(path)
export_inventory_csv(path)
export_transactions_csv(path)
export_shipments_csv(path)
preview_parts_import_csv(path)
import_parts_csv(path)
preview_inventory_import_csv(path)
import_inventory_csv(path)
```

Rules:

- Import must validate data before committing.
- Show preview and errors before import.
- Create backup before import.
- Do not silently skip invalid rows.
- Export files should include timestamps in filenames.

---

# 8. Required Workflows

## 8.1 Workflow: First Launch

When the app runs for the first time:

1. Create required folders:
   - `data/`
   - `backups/`
   - `exports/`
   - `logs/`
2. Create SQLite database if missing.
3. Run schema creation.
4. Create default locations:
   - Receiving
   - Stock
   - Shipping Bench
   - Scrap
5. Ask for operator name or show operator name field in header.
6. Open Dashboard.

Acceptance criteria:

- App launches without command-line interaction.
- Database is created automatically.
- Default locations exist.
- Dashboard loads without sample data.

## 8.2 Workflow: Add a Part

User story:

```text
As an operator, I want to add a new part so that inventory can be tracked.
```

Required fields:

```text
Part number
Description
```

Optional fields:

```text
Barcode
Category
Unit of measure
Default location
Minimum quantity
Revision
Notes
```

Steps:

1. User opens Parts screen.
2. User clicks `Add Part`.
3. User enters required fields.
4. User clicks `Save Part`.
5. App validates inputs.
6. App creates part.
7. App shows success confirmation.

Success message:

```text
Part created: ABC-123 — Bearing Assembly
```

Validation messages:

```text
Part number is required.
Description is required.
A part with this part number already exists.
Minimum quantity cannot be negative.
```

Acceptance criteria:

- Part appears in search results immediately.
- Duplicate part numbers are blocked.
- User can cancel without saving.

## 8.3 Workflow: Search for a Part

User story:

```text
As an operator, I want to quickly find parts by part number, description, barcode, or location.
```

Search should match:

- Part number
- Partial part number
- Description
- Barcode
- Category

Search behavior:

- Case-insensitive
- Partial match
- Results update quickly
- Inactive parts hidden by default

Acceptance criteria:

- Searching `6205` finds `BRG-6205`.
- Searching `bearing` finds descriptions containing bearing.
- Barcode scanner input can populate the search field.

## 8.3A Workflow: Define and Visualize a Nested BOM

User story:

```text
As an operator, I want to define the components used by a shipped assembly so that shipping can automatically deduct the correct parts.
```

Required fields:

```text
Parent part
Component part
Quantity per parent
```

Steps:

1. User opens BOM screen.
2. User selects parent assembly/kit part.
3. User selects component part.
4. User enters quantity required per parent.
5. App validates that both parts exist, quantity is positive, and the link will not create a circular BOM.
6. App saves or updates the component link.
7. App shows the nested BOM tree.
8. App shows flattened leaf component requirements for a selected ship quantity/location.
9. App highlights shortages before the user ships.

Acceptance criteria:

- Nested BOMs can be multiple levels deep.
- Circular BOMs are blocked.
- Duplicate leaf components are aggregated in flattened requirements.
- Tree visualization shows intermediate assemblies.
- Requirement preview shows required, available, and shortage quantities.

## 8.4 Workflow: Receive Stock

User story:

```text
As an operator, I want to receive stock so that inventory increases and the transaction is recorded.
```

Required fields:

```text
Part
Quantity
Location
Operator name
```

Optional fields:

```text
Reference
Notes
```

Steps:

1. User opens Receive Stock screen.
2. User searches/selects part.
3. App shows current stock for selected location and total stock.
4. User enters quantity.
5. User selects location.
6. User enters reference/notes if needed.
7. User clicks `Receive Stock`.
8. App validates inputs.
9. App updates inventory balance.
10. App creates `RECEIVE` transaction.
11. App shows confirmation.

Success message:

```text
Done — 10 units received for ABC-123.
Current stock in Stock: 25.
```

Acceptance criteria:

- Quantity must be greater than zero.
- Inventory balance increases.
- Transaction history shows the receive transaction.
- Operator name is stored.

## 8.5 Workflow: Ship Stock

User story:

```text
As an operator, I want to ship stock or a BOM parent so that inventory decreases, component usage is recorded, and shipment details are traceable.
```

Required fields:

```text
Part
Quantity
Location
Recipient
Operator name
```

Optional fields:

```text
Carrier
Tracking number
Reference
Notes
```

Steps:

1. User opens Ship Stock screen.
2. User searches/selects part.
3. App shows available stock at selected location, or BOM component availability if the part has a BOM.
4. User enters quantity.
5. User enters recipient/project/reference.
6. User enters carrier/tracking if available.
7. App previews remaining stock or BOM component shortages.
8. User clicks `Ship Stock`.
9. App validates enough stock exists for a normal part, or enough leaf component stock exists for a BOM parent.
10. App creates shipment record.
11. For a normal part, app reduces that part's inventory balance and creates a linked `SHIP` transaction.
12. For a BOM parent, app deducts required leaf components, creates linked `BOM_CONSUME` transactions, and creates a `SHIP_BOM` parent trace transaction.
13. App stores shipment component snapshots for BOM shipments.
14. App shows confirmation.

Preview text:

```text
Available in Stock: 12
After shipment: 7
```

Success message:

```text
Done — 5 units shipped for ABC-123.
Shipment: SHP-20260521-0001
Remaining in Stock: 7.
```

Validation messages:

```text
Quantity must be greater than zero.
Recipient is required.
Not enough stock in Stock. Available: 3, requested: 5.
Not enough BOM component stock for ABC-123. BRG-6205: available 3, required 5.
```

Acceptance criteria:

- Cannot ship more than available stock.
- Cannot ship a BOM parent when any required leaf component is short.
- Shipment record is created.
- Inventory balance decreases for the shipped normal part or the required BOM leaf components.
- Transaction history shows a linked `SHIP`, or `SHIP_BOM` plus linked `BOM_CONSUME` rows.
- Shipment details preserve the exact BOM component quantities consumed.

## 8.6 Workflow: Move Stock

User story:

```text
As an operator, I want to move stock between locations so that the app reflects where inventory physically is.
```

Required fields:

```text
Part
Quantity
From location
To location
Operator name
```

Optional fields:

```text
Reference
Notes
```

Steps:

1. User opens Move / Adjust screen.
2. User selects `Move Stock` mode.
3. User selects part.
4. User selects source and destination locations.
5. User enters quantity.
6. App validates enough stock exists at source.
7. App reduces source balance.
8. App increases destination balance.
9. App creates `MOVE_OUT` transaction.
10. App creates `MOVE_IN` transaction.
11. App shows confirmation.

Validation:

- Source and destination cannot be the same.
- Quantity must be greater than zero.
- Cannot move more than available source stock.

Acceptance criteria:

- Source location decreases.
- Destination location increases.
- Two transaction rows are created.

## 8.7 Workflow: Adjust / Correct Stock Count

User story:

```text
As an operator, I want to correct stock after a physical count so that the system matches reality.
```

Required fields:

```text
Part
Location
New counted quantity
Reason
Operator name
```

Optional fields:

```text
Notes
```

Steps:

1. User opens Move / Adjust screen.
2. User selects `Adjust Count` mode.
3. User selects part and location.
4. App shows current system quantity.
5. User enters actual counted quantity.
6. User enters reason.
7. App calculates difference.
8. App asks for confirmation if difference is large.
9. App updates balance.
10. App creates `COUNT_CORRECTION` transaction with quantity difference.
11. App shows confirmation.

Example:

```text
Current system quantity: 10
Actual counted quantity: 8
Difference: -2
```

Success message:

```text
Done — count corrected for ABC-123.
Previous: 10. New: 8. Difference: -2.
```

Validation:

- New counted quantity cannot be negative.
- Reason is required.

Acceptance criteria:

- Balance equals the new counted quantity.
- Transaction records the difference, not the final count.
- Reason is stored.

## 8.8 Workflow: Low-Stock Alerts

User story:

```text
As an operator, I want to see low-stock parts so that I know what needs attention.
```

Rules:

- A part is low stock when total quantity across active locations is less than or equal to `minimum_quantity`.
- Parts with `minimum_quantity = 0` can be ignored unless quantity is also 0 and user enables zero-stock visibility.

Dashboard should show:

```text
Low Stock
ABC-123 — Current: 3, Minimum: 5
XYZ-999 — Current: 0, Minimum: 2
```

Acceptance criteria:

- Low-stock list updates after receive, ship, move, and adjust actions.
- Clicking a low-stock item opens the part detail.

---

# 9. UI Screen Requirements

## 9.1 Main Window

Use a clean desktop layout:

```text
┌──────────────────────────────────────────────┐
│ Header: Search | Operator | Status           │
├───────────────┬──────────────────────────────┤
│ Sidebar       │ Main Content                 │
│               │                              │
│ Dashboard     │                              │
│ Parts         │                              │
│ BOM           │                              │
│ Receive       │                              │
│ Ship          │                              │
│ Move/Adjust   │                              │
│ History       │                              │
│ Settings      │                              │
└───────────────┴──────────────────────────────┘
```

Header requirements:

- Global search field
- Operator name field
- Small status indicator

Sidebar requirements:

- Large readable navigation labels
- Active screen highlighted
- Do not overcrowd with too many items

## 9.2 Dashboard View

Purpose:

```text
What needs attention now?
```

Show:

- Big quick-action buttons:
  - Receive Stock
  - Ship Stock
  - Find Part
  - BOM Trace
- Low-stock card
- Recent activity card
- Recent shipments card

Acceptance criteria:

- User can start common tasks from dashboard.
- Recent activity updates after transactions.

## 9.3 Parts View

Purpose:

```text
Find, create, and maintain part records.
```

Must include:

- Search field
- Add Part button
- Results list
- Part detail panel
- Edit Part button
- Active/inactive toggle
- Current stock summary
- Recent transactions for selected part

Avoid overwhelming users with too many columns.

Suggested visible result fields:

```text
Part Number | Description | Total Stock | Status
```

## 9.4 BOM View

Purpose:

```text
Define and trace nested assemblies, kits, and component usage.
```

Must include:

- Parent part selector
- Component part selector
- Quantity per parent field
- Add/update component action
- Direct component list
- Remove component action
- Nested BOM tree visualization
- Ship quantity input for requirement preview
- Location selector for availability checks
- Flattened component requirements table
- Shortage status before shipping

## 9.5 Receive Stock View

Purpose:

```text
Add inventory.
```

Must include:

- Part search/autocomplete
- Quantity input
- Location dropdown
- Reference field
- Notes field
- Current stock display
- Primary button: `Receive Stock`

## 9.6 Ship Stock View

Purpose:

```text
Reduce inventory and create shipment record.
```

Must include:

- Part search/autocomplete
- Quantity input
- Location dropdown
- Recipient field
- Carrier field
- Tracking number field
- Reference field
- Notes field
- Available stock display
- Remaining stock preview for normal parts
- BOM component availability and shortage preview for BOM parents
- Primary button: `Ship Stock`

## 9.7 Move / Adjust View

Purpose:

```text
Move stock or correct stock count.
```

Use two modes:

```text
Move Stock
Adjust Count
```

Move Stock fields:

```text
Part
Quantity
From location
To location
Reference
Notes
```

Adjust Count fields:

```text
Part
Location
New counted quantity
Reason
Notes
```

## 9.8 History View

Purpose:

```text
Trace what happened.
```

Filters:

- Date range
- Part
- Transaction type
- Operator
- Reference

Visible columns:

```text
Date | Type | Part | Quantity | From | To | Operator | Reference
```

Must include:

- Clear filters button
- Export visible history button

## 9.9 Settings View

Purpose:

```text
Basic app maintenance.
```

Must include:

- Default operator name
- Backup folder path display
- Create Backup Now button
- Open Backup Folder button
- Export folder path display
- Open Export Folder button
- App version

---

# 10. Validation Rules

## 10.1 General Validation

- Required fields cannot be blank.
- Quantity must be an integer.
- Stock-changing quantities must be positive, except internal transaction differences.
- Operator name is required for all stock actions.
- Notes can be optional.

## 10.2 Inventory Validation

- Cannot ship more than available stock.
- Cannot move more than available stock.
- Cannot scrap more than available stock.
- Cannot create negative stock in MVP.
- Adjustment new count cannot be negative.

## 10.3 Part Validation

- Part number required.
- Description required.
- Part number unique.
- Barcode unique if provided.
- Minimum quantity cannot be negative.

## 10.4 Shipment Validation

- Recipient required.
- Quantity required.
- Quantity positive.
- Shipment number unique.

---

# 11. Error Handling Requirements

## 11.1 User-Facing Errors

All user-facing errors should be plain language.

Examples:

```text
Please select a part before receiving stock.
Quantity must be greater than zero.
Not enough stock in Rack A. Available: 3, requested: 5.
This part cannot be deleted because it has inventory history. Mark it inactive instead.
```

## 11.2 Developer Logs

Technical details should go to a log file, not the user.

Example log folder:

```text
logs/app.log
```

Log:

- App startup
- Database creation
- Backups
- Imports
- Exports
- Exceptions

---

# 12. Backup and Recovery

## 12.1 Backup Requirements

Create backups:

- On app startup
- Before CSV import
- When user clicks `Create Backup Now`

Keep latest 20 backups by default.

## 12.2 Restore Process for MVP

Full in-app restore is not required for MVP.

Document a manual restore process:

```text
1. Close the app.
2. Go to backups folder.
3. Copy desired backup file.
4. Rename it to inventory.db.
5. Replace data/inventory.db.
6. Restart the app.
```

Add this instruction to README later.

---

# 13. CSV Import and Export

## 13.1 Export Requirements

Export to CSV:

- Parts
- Current inventory
- Transaction history
- Shipments

Export file names should include timestamps:

```text
parts_20260521_093000.csv
inventory_20260521_093000.csv
transactions_20260521_093000.csv
shipments_20260521_093000.csv
```

## 13.2 Parts Import CSV Format

Required columns:

```text
part_number,description
```

Optional columns:

```text
barcode,category,unit_of_measure,default_location,minimum_quantity,revision,notes
```

Example:

```csv
part_number,description,barcode,category,unit_of_measure,default_location,minimum_quantity,revision,notes
ABC-123,Bearing Assembly,ABC123,Mechanical,ea,Stock,5,A,Common replacement part
XYZ-999,Control Cable,,Electrical,ea,Stock,2,,
```

## 13.3 Initial Inventory Import CSV Format

Required columns:

```text
part_number,location,quantity
```

Optional columns:

```text
reference,notes
```

Example:

```csv
part_number,location,quantity,reference,notes
ABC-123,Stock,10,Initial import,Imported from spreadsheet
XYZ-999,Stock,4,Initial import,Imported from spreadsheet
```

Import behavior:

- Validate all rows first.
- Create backup before import.
- For initial inventory, create `RECEIVE` or `COUNT_CORRECTION` transactions.
- Do not import invalid rows silently.

---

# 14. Testing Plan

## 14.1 Minimum Automated Tests

Use `pytest` for service-layer tests.

Test files:

```text
tests/test_part_service.py
tests/test_inventory_service.py
tests/test_shipment_service.py
tests/test_bom_service.py
tests/test_import_export_service.py
```

## 14.2 Required Test Cases

Part tests:

- Create valid part
- Reject duplicate part number
- Reject missing part number
- Reject negative minimum quantity
- Search by part number
- Search by description

Inventory tests:

- Receive stock increases balance
- Receive stock creates transaction
- Ship stock decreases balance
- Ship stock creates transaction
- Ship stock creates shipment
- Ship stock rejects insufficient quantity
- Move stock updates both locations
- Move stock creates move-out and move-in transactions
- Adjust stock sets balance to new count
- Adjust stock records difference
- Reject negative adjustment count

BOM tests:

- Add direct BOM component
- Reject circular BOM
- Reject non-positive component quantity
- Expand nested BOM to leaf component requirements
- Aggregate duplicate leaf components
- Report component availability and shortages
- Ship BOM parent deducts leaf components
- Ship BOM parent creates shipment component snapshots
- Ship BOM parent creates linked `SHIP_BOM` and `BOM_CONSUME` transactions
- BOM shipment shortage does not change balances or create shipment records

Backup tests:

- Backup file is created
- Backup filename includes timestamp
- Old backups are cleaned up after keep limit

Import/export tests:

- Export creates CSV file
- Import rejects invalid missing fields
- Import rejects unknown locations
- Import preview reports row errors

## 14.3 Manual Testing Checklist

Before calling MVP complete, manually verify:

```text
[ ] App launches with no database present.
[ ] Default locations are created.
[ ] Operator name can be entered.
[ ] Add part works.
[ ] Duplicate part number is blocked.
[ ] Search finds part by part number.
[ ] Search finds part by description.
[ ] BOM screen adds a component to a parent.
[ ] BOM screen blocks circular relationships.
[ ] BOM tree shows nested components.
[ ] BOM requirements preview shows shortages.
[ ] Receive stock updates quantity.
[ ] Receive stock shows success message.
[ ] Ship stock blocks insufficient stock.
[ ] Ship BOM parent blocks insufficient component stock.
[ ] Ship BOM parent deducts required leaf components.
[ ] Ship BOM parent creates linked component trace rows.
[ ] Ship stock creates shipment number.
[ ] Move stock changes both locations.
[ ] Adjust stock requires reason.
[ ] Low-stock list updates.
[ ] History filters work.
[ ] CSV export creates files.
[ ] Backup is created at startup.
[ ] Manual backup button works.
[ ] User-facing errors are understandable.
```

---

# 15. Development Phases

## Phase 0 — Setup and Skeleton

Goal: Create a runnable empty app.

Tasks:

```text
[ ] Create project folder structure.
[ ] Create virtual environment.
[ ] Create requirements.txt.
[ ] Add app.py entry point.
[ ] Add basic PySide6 main window.
[ ] Add sidebar navigation placeholder.
[ ] Add empty views for Dashboard, Parts, Receive, Ship, Move/Adjust, History, Settings.
[ ] Add config paths for data, backups, exports, logs.
```

Done when:

```text
App opens and user can switch between empty screens.
```

## Phase 1 — Database Foundation

Goal: Create reliable local database setup.

Tasks:

```text
[ ] Add SQLAlchemy database engine/session setup.
[ ] Create ORM models.
[ ] Create database initialization function.
[ ] Auto-create data folder.
[ ] Auto-create SQLite database if missing.
[ ] Add default locations.
[ ] Add settings table.
[ ] Add startup backup function.
```

Done when:

```text
App starts, creates database, creates default locations, and creates backup.
```

## Phase 2 — Parts Management

Goal: Add and find parts.

Tasks:

```text
[ ] Implement PartService.
[ ] Build Parts View search UI.
[ ] Build Add/Edit Part dialog.
[ ] Add validation messages.
[ ] Add active/inactive handling.
[ ] Show selected part details.
[ ] Show current stock summary placeholder.
```

Done when:

```text
User can create, edit, deactivate, and search parts.
```

## Phase 3 — Inventory Core

Goal: Make inventory quantities work.

Tasks:

```text
[ ] Implement InventoryService balance helpers.
[ ] Implement receive_stock.
[ ] Implement ship_stock without UI shipment details first if needed.
[ ] Implement move_stock.
[ ] Implement adjust_stock.
[ ] Ensure every change creates transaction records.
[ ] Add database transaction handling.
[ ] Add service-layer tests.
```

Done when:

```text
Inventory can be received, shipped, moved, and adjusted through service methods with tests passing.
```

## Phase 3B — Nested BOM Core

Goal: Make component usage traceable when assemblies or kits are shipped.

Tasks:

```text
[x] Add in-memory BOM component model.
[x] Implement add/remove BOM component links.
[x] Block circular BOMs.
[x] Implement recursive BOM tree and flattened leaf requirements.
[x] Validate component shortages before BOM shipment.
[x] Deduct BOM leaf components on shipment.
[x] Create `SHIP_BOM` and linked `BOM_CONSUME` transaction rows.
[x] Store shipment component consumption snapshots.
[x] Add BOM service/store tests.
[ ] Migrate BOM tables to SQLAlchemy persistence.
```

Done when:

```text
Shipping a BOM parent deducts the correct nested leaf components and leaves a readable shipment/transaction trace.
```

## Phase 4 — Receive and Ship UI

Goal: Operators can perform core stock tasks in the app.

Tasks:

```text
[ ] Build Receive Stock screen.
[ ] Add part autocomplete/search.
[ ] Add location dropdown.
[ ] Show current stock.
[ ] Show success confirmation.
[ ] Build Ship Stock screen.
[ ] Show available and remaining stock preview.
[x] Show BOM component availability and shortages for BOM parents in the in-memory UI.
[ ] Add recipient/carrier/tracking/reference fields.
[ ] Create shipment record during shipping.
[ ] Show shipment number after success.
```

Done when:

```text
A user can receive and ship stock without touching the database directly.
```

## Phase 5 — Move / Adjust UI

Goal: Operators can correct and relocate stock.

Tasks:

```text
[ ] Build Move / Adjust screen.
[ ] Add mode toggle for Move Stock and Adjust Count.
[ ] Validate source/destination location.
[ ] Require reason for adjustment.
[ ] Show before/after quantities.
[ ] Add confirmation for large adjustments.
```

Done when:

```text
A user can move stock and correct stock count with clear audit history.
```

## Phase 6 — Dashboard and History

Goal: Improve visibility and traceability.

Tasks:

```text
[ ] Build Dashboard quick actions.
[ ] Add low-stock card.
[ ] Add recent activity card.
[ ] Add recent shipments card.
[ ] Build History screen.
[ ] Add filters.
[ ] Add clear filters button.
[ ] Add export visible history action.
```

Done when:

```text
User can see what needs attention and trace recent inventory changes.
```

## Phase 7 — Import, Export, and Backup Polish

Goal: Support Excel migration and safe testing.

Tasks:

```text
[ ] Implement CSV export for parts.
[ ] Implement CSV export for current inventory.
[ ] Implement CSV export for transactions.
[ ] Implement CSV export for shipments.
[ ] Implement CSV import preview for parts.
[ ] Implement CSV import preview for initial inventory.
[ ] Create backup before import.
[ ] Show import validation errors.
[ ] Add manual backup button.
[ ] Add open backup/export folder buttons.
```

Done when:

```text
User can import starter data, export records, and create backups from the UI.
```

## Phase 8 — MVP Hardening

Goal: Make it stable enough for non-production use.

Tasks:

```text
[ ] Add friendly error handling throughout UI.
[ ] Add application logging.
[ ] Confirm no raw stack traces are shown to users.
[ ] Run manual testing checklist.
[ ] Fix high-friction UI issues.
[ ] Add README with setup and restore instructions.
[ ] Optional: package with PyInstaller.
```

Done when:

```text
A junior operator can complete normal workflows without developer assistance.
```

---

# 16. Acceptance Criteria for Complete MVP

The MVP is complete when all of these are true:

```text
[ ] App runs locally.
[ ] App creates its own SQLite database.
[ ] App creates default locations.
[ ] App creates startup backups.
[ ] User can create and edit parts.
[ ] User can search parts.
[ ] User can define nested BOMs.
[ ] User can visualize BOM trees and flattened component requirements.
[ ] User can receive stock.
[ ] User can ship stock.
[ ] User can ship a BOM parent and automatically consume required components.
[ ] User can move stock.
[ ] User can adjust stock count.
[ ] Every inventory change creates transaction history.
[ ] Shipping creates shipment records.
[ ] BOM shipments create component consumption snapshots.
[ ] Negative inventory is blocked.
[ ] BOM component shortages are blocked before any stock changes.
[ ] Low-stock alerts work.
[ ] Dashboard shows recent activity.
[ ] History screen supports filtering.
[ ] CSV export works.
[ ] CSV import validates data before commit.
[ ] Manual backup works.
[ ] Errors are user-friendly.
[ ] Basic service-layer tests pass.
```

---

# 17. Junior Developer Implementation Notes

## 17.1 Do Not Put Business Logic in UI Files

Bad:

```text
Button click directly updates database rows.
```

Good:

```text
Button click calls InventoryService.receive_stock(...).
```

The UI should gather input, call a service, then display the result.

## 17.2 Use Database Transactions for Multi-Step Actions

Shipping requires multiple things:

```text
Create shipment
Reduce inventory balance
Create inventory transaction
```

These must succeed or fail together.

If one fails, none should be committed.

## 17.3 Avoid Hard Deletes

Do not delete:

- Parts with history
- Locations with history
- Inventory transactions
- Shipments

Use inactive flags for parts and locations.

## 17.4 Keep Error Messages Human

Catch expected validation problems and show plain-language messages.

Unexpected exceptions should be logged and shown as:

```text
Something went wrong while saving. No changes were made. Please try again or contact the developer.
```

## 17.5 Build Service Tests Before Fancy UI

The inventory logic matters more than the visual polish.

Before polishing UI, make sure service tests pass for:

- receive
- ship
- move
- adjust
- insufficient stock

## 17.6 Keep UI Fields Consistent

Use consistent labels across screens:

```text
Part
Quantity
Location
Reference
Operator
Notes
```

Do not call the same thing `item`, `part`, and `SKU` in different places unless there is a clear reason.

## 17.7 Use Clear Transaction Type Constants

Define transaction types once.

Example:

```text
RECEIVE
SHIP
SHIP_BOM
BOM_CONSUME
MOVE_OUT
MOVE_IN
COUNT_CORRECTION
SCRAP
RETURN
```

Avoid typos like:

```text
Recieve
received
RECEIVED
```

## 17.8 Keep the App Recoverable

Before risky actions, create backups.

Risky actions include:

- CSV import
- Schema changes
- Bulk updates

---

# 18. Future Enhancements After MVP

Only consider these after the MVP is being used and real pain points are known.

## 18.1 Likely Next Enhancements

- Multi-line shipments
- Packing slip PDF
- Label printing
- Supplier field on parts
- Customer/project list
- Purchase order-lite workflow
- Reorder suggestions
- More advanced CSV import mapping
- Better barcode workflows
- Packaging as executable

## 18.2 Advanced Enhancements

- Serial number tracking
- Lot/batch tracking
- Expiration dates
- Role-based permissions
- Multi-user database
- PostgreSQL backend
- Web app version
- REST API
- Power BI export/integration
- Carrier integrations
- Accounting integration

---

# 19. Risk Register

## Risk: Scope Creep

Mitigation:

- Keep MVP limited to parts, inventory, transactions, and simple shipping.
- Put nice-to-have features into future enhancements.

## Risk: Inventory Balance Drift

Mitigation:

- Only services can update balances.
- Every balance change creates transaction records.
- Add future utility to recalculate balances from transactions.

## Risk: Operators Avoid the App

Mitigation:

- Make common workflows faster than Excel.
- Use clear success messages.
- Reduce typing.
- Keep UI simple.

## Risk: Data Loss

Mitigation:

- Startup backups.
- Pre-import backups.
- Manual backup button.
- Keep latest 20 backups.

## Risk: Bad Import Data

Mitigation:

- Preview imports.
- Validate all rows.
- Show errors before committing.
- Create backup before import.

## Risk: UI Becomes Too Dense

Mitigation:

- Use task-based screens.
- Hide advanced fields.
- Keep one primary action per screen.
- Avoid spreadsheet-like layouts where possible.

---

# 20. Recommended First Development Sprint

If starting immediately, build this first:

```text
Sprint 1 Goal: App skeleton + database + parts
```

Tasks:

```text
[ ] Create project structure.
[ ] Create PySide6 main window.
[ ] Add sidebar navigation.
[ ] Add SQLite/SQLAlchemy setup.
[ ] Create models for Part, Location, Setting.
[ ] Create default locations on startup.
[ ] Build Parts screen.
[ ] Implement add/edit/search part.
[ ] Add friendly validation messages.
```

Sprint 1 demo should show:

```text
Open app
→ Add part ABC-123
→ Search ABC
→ Edit description
→ Mark inactive
→ Search active parts only
```

Do not build receiving/shipping until part management is stable.

---

# 21. Final MVP North Star

The app should feel like this:

```text
I know what to click.
I know what happened.
I can find what I need.
I cannot accidentally break inventory easily.
If something goes wrong, there is a backup.
```

If the MVP achieves that, it is successful.
