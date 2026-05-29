For a non-production ERP replacement focused on **inventory, part tracking, and shipping**, the main goal should be:

> **Make the correct action obvious, make mistakes hard, and make recovery easy.**

Especially if operators are less technical or ADHD-prone, the app should reduce cognitive load, avoid clutter, and guide users through one task at a time.

***

# 1. Revised Philosophy

## Keep the system boring internally, pleasant externally

For now, the system should be:

* local-first
* simple to install
* hard to misuse
* fast to operate
* easy to recover from mistakes
* searchable
* visually clear
* transaction-based

Avoid trying to build a full ERP too soon.

This is not yet a production-grade ERP. It is more like:

> **A structured inventory and shipping control app that replaces messy Excel sheets.**

That framing keeps the scope sane.

***

# 2. Biggest Pitfalls to Catch Early

## Pitfall 1: Too many modules too soon

The previous plan included:

* suppliers
* purchase orders
* sales orders
* shipments
* users
* reporting
* barcode support
* roles
* PDFs
* dashboards

All useful eventually — but risky at the start.

### Recommendation

Start with only four core workflows:

1. **Create / edit parts**
2. **Receive stock**
3. **Move / adjust stock**
4. **Ship stock**

Everything else should support those workflows.

***

## Pitfall 2: Inventory quantity stored in too many places

A common ERP mistake is storing current quantity in one table, transaction history in another, and then letting them drift apart.

Example problem:

```text
inventory.quantity says 10
transaction history adds up to 8
Which one is correct?
```

### Recommendation

For the MVP, use a hybrid approach:

* Keep a current quantity table for speed and simplicity.
* Also log every change in an inventory transaction table.
* Add a simple “recalculate stock from transactions” utility for debugging.

This keeps the app usable while providing an audit trail.

***

## Pitfall 3: Making shipping too complex

A full shipping system can quickly become overwhelming:

* carriers
* rates
* labels
* customs
* packing slips
* partial shipments
* backorders
* returns

For now, do not build that.

### MVP shipping should mean:

```text
Select part → enter quantity → enter destination/reference → mark shipped
```

Optional fields:

* customer / recipient
* tracking number
* carrier
* notes

No carrier API.  
No automatic label generation yet.  
No customs workflow.  
No rate shopping.

***

## Pitfall 4: User roles too early

User roles sound responsible, but for a non-production local app they create friction.

### Recommendation

Start with no login or a very simple operator name prompt.

Example:

```text
Operator name: Theo
```

Then every transaction records:

```text
who did it
when
what changed
why/reference
```

Later, this can become proper authentication if needed.

***

## Pitfall 5: Designing for database purity instead of human flow

Operators do not think in database tables.

They think:

```text
I received parts.
I need to ship this.
Where is this part?
Did we already send it?
Why is stock wrong?
```

### Recommendation

Design screens around jobs, not tables.

Good:

```text
Receive Stock
Ship Stock
Find a Part
Inventory Count
Recent Activity
```

Less good:

```text
Parts Table
Inventory Table
Transactions Table
Shipment Table
```

The database can be normalized; the UI should be task-based.

***

# 3. Recommended MVP Scope

## MVP should include

### Parts

* Part number / SKU
* Description
* Category
* Default location
* Unit of measure
* Active/inactive
* Notes

Optional but useful:

* barcode value
* revision
* supplier part number

***

### Inventory

* Quantity on hand
* Location
* Minimum stock level
* Last updated date

For now, avoid advanced inventory concepts unless truly needed:

* lots
* serial numbers
* expiry dates
* bin hierarchies
* multi-warehouse transfers
* costing layers

Add those later only if the workflow requires them.

***

### Transactions

Every stock change creates a transaction.

Transaction types:

```text
RECEIVE
SHIP
ADJUST
MOVE
COUNT_CORRECTION
SCRAP
RETURN
```

Each transaction should store:

* part
* quantity change
* from location
* to location
* reference
* operator
* timestamp
* notes

This is the heart of traceability.

***

### Shipping

Simple shipment records:

* shipment number
* date
* part
* quantity
* recipient/customer/project
* carrier
* tracking number
* operator
* notes

Important: shipping should automatically deduct inventory.

***

# 4. Simplified Database Model

I would reduce the original schema.

## Keep these tables initially

```text
parts
locations
inventory_balances
inventory_transactions
shipments
settings
```

Optional later:

```text
suppliers
purchase_orders
customers
users
attachments
```

***

## Why this simpler model is better

The first version does not need separate sales orders, purchase orders, or supplier workflows.

Instead:

* receiving stock can use a free-text reference
* shipping can use a free-text customer/project/reference
* purchasing can remain outside the app for now
* the app still captures movement history

This avoids creating fake business processes before the real workflow is understood.

***

# 5. Suggested Local Tech Stack

The original stack is mostly right.

## Recommended stack

```text
Python
SQLite
SQLAlchemy
PySide6
```

This gives you:

* desktop app feel
* offline use
* a single local database file
* modern UI potential
* easier packaging later

***

## Avoid initially

```text
Flask / FastAPI
```

A web app sounds flexible, but introduces more setup:

* local server
* browser issues
* ports
* multi-user assumptions
* deployment decisions

For a non-production local tool, a desktop app is probably smoother.

***

# 6. ADHD-Friendly / Low-Friction UX Principles

Not medical advice, but from a usability standpoint, “ADHD-friendly” usually means reducing attention burden and decision fatigue.

## Design principles

### 1. One primary action per screen

Each screen should have one obvious job.

Example:

```text
Receive Stock
```

Primary button:

```text
Receive Items
```

Avoid five competing buttons.

***

### 2. Use progressive disclosure

Do not show every field at once.

Basic view:

```text
Part number
Quantity
Location
Reference
```

Advanced section, collapsed by default:

```text
Notes
Supplier
Revision
Internal comments
Override date
```

***

### 3. Strong visual hierarchy

Use:

* large page titles
* clear sections
* big primary buttons
* consistent button placement
* subtle color coding
* plain language

Example:

```text
Green = Receive
Blue = Move
Orange = Adjust
Red = Ship / Reduce Stock
```

But never rely on color alone — include text and icons.

***

### 4. Search should be excellent

This may be the most important usability feature.

Operators should be able to search by:

* part number
* partial description
* barcode
* location
* reference
* shipment number

Search should tolerate partial entries.

Example:

```text
6205
bearing
rack a
SO-1044
```

***

### 5. Confirm destructive or unusual actions

Normal receiving should be quick.

But risky actions need confirmation:

* shipping more than available
* negative inventory
* deleting a part
* large adjustment
* changing part number
* editing old transactions

Example:

```text
You are about to reduce stock by 25 units.
Current stock: 30
Remaining stock: 5

Continue?
```

***

### 6. Make errors helpful, not technical

Bad:

```text
IntegrityError: FOREIGN KEY constraint failed
```

Good:

```text
This part cannot be deleted because it has inventory history.
Mark it inactive instead.
```

***

### 7. Provide a recent activity feed

This helps operators recover context.

Dashboard should show:

```text
Recently received
Recently shipped
Recent adjustments
Low-stock items
```

For ADHD-friendly workflows, this is valuable because it externalizes memory.

***

### 8. Reduce typing

Use:

* dropdowns
* autocomplete
* barcode scanner support
* default locations
* saved recent values
* duplicate previous entry
* quick actions

Example:

```text
Receive another item like this
```

or

```text
Use last location
```

***

### 9. Add “undo-style” correction, not true undo

Inventory systems should usually not erase history.

Instead of undoing transactions, create reversing transactions.

Example:

Original:

```text
SHIP -5
```

Correction:

```text
RETURN +5
```

The UI can call it:

```text
Correct this transaction
```

But internally, it preserves audit history.

***

# 7. Recommended Screen List

Keep the app to about six main screens.

## 1. Dashboard

Purpose: “What needs attention?”

Show:

* low stock
* recent shipments
* recent receipts
* inventory warnings
* quick buttons

Primary actions:

```text
Receive Stock
Ship Stock
Find Part
```

***

## 2. Parts

Purpose: manage part master data.

Features:

* search
* add part
* edit part
* mark inactive
* view stock
* view history

Avoid exposing raw database-like grids too much.

***

## 3. Receive Stock

Purpose: add inventory.

Fields:

```text
Part
Quantity
Location
Reference
Operator
Notes
```

After submit:

```text
Stock updated.
New quantity: 42
```

Then show quick actions:

```text
Receive another
View part
Print label later
```

***

## 4. Ship Stock

Purpose: reduce inventory and record shipment.

Fields:

```text
Part
Quantity
Recipient / project
Location
Carrier
Tracking number
Operator
Notes
```

Before submit:

```text
Current stock: 42
After shipment: 37
```

This gives operators confidence.

***

## 5. Move / Adjust Stock

Purpose: fix or relocate inventory.

Split into two modes:

```text
Move stock
Adjust stock
```

Move:

```text
Rack A → Rack B
```

Adjust:

```text
Expected 10, counted 8
Reason required
```

Require a reason for adjustments.

***

## 6. Activity / History

Purpose: traceability.

Filters:

* part
* date
* operator
* transaction type
* reference

Export to CSV if needed.

***

# 8. Data Model Revisions

Here is the improved conceptual model.

## parts

```text
id
part_number
description
category
unit_of_measure
default_location_id
minimum_quantity
barcode
revision
active
notes
created_at
updated_at
```

***

## locations

```text
id
name
description
active
```

Examples:

```text
Receiving
Rack A
Rack B
Shipping Bench
Scrap
```

***

## inventory\_balances

```text
id
part_id
location_id
quantity
updated_at
```

Unique rule:

```text
one balance per part per location
```

***

## inventory\_transactions

```text
id
part_id
transaction_type
quantity_change
from_location_id
to_location_id
reference
operator_name
notes
created_at
```

Important:

* receiving has positive quantity
* shipping has negative quantity
* moves may create a transfer record
* adjustments record the difference

***

## shipments

```text
id
shipment_number
part_id
quantity
location_id
recipient
carrier
tracking_number
operator_name
notes
created_at
```

For now, one part per shipment is acceptable.

Later, if needed, split into:

```text
shipments
shipment_lines
```

But do not start there unless multi-line shipments are immediately required.

***

# 9. Important Design Decisions to Make Early

These are worth deciding now because they affect the database.

## Decision 1: Can inventory go negative?

Recommended default:

```text
No
```

But allow admin override later.

For MVP:

```text
Block shipping if quantity is insufficient.
```

Message:

```text
Not enough stock in Rack A.
Available: 3
Requested: 5
```

***

## Decision 2: Are serial numbers required?

If every individual part must be tracked separately, the design changes significantly.

For non-production MVP, I would avoid serial tracking unless absolutely required.

Use this for now:

```text
part-level quantity tracking
```

Not this:

```text
each physical unit has its own identity
```

***

## Decision 3: Are lots/batches required?

Same issue as serials.

Avoid initially unless traceability requires it.

***

## Decision 4: Multi-location or single-location?

I recommend adding locations from the beginning, but keeping them simple.

Even if there is only one stockroom, locations help later.

Examples:

```text
Receiving
Stock
Shipping
Scrap
```

***

## Decision 5: Do you need attachments?

Probably not in MVP.

Instead, use notes and references.

Add file attachments later.

***

# 10. What I Would Remove From the Original Plan for Now

To keep it lean, I would postpone:

* purchase orders
* sales orders
* customer database
* supplier database
* user permissions
* formal accounting
* inventory valuation
* PDF generation
* carrier integrations
* automatic label printing
* multi-company support
* cloud sync
* advanced dashboards
* APIs

These are not bad ideas. They are just not MVP.

***

# 11. What I Would Keep From the Original Plan

Definitely keep:

* SQLite
* transaction history
* parts database
* inventory balances
* shipping records
* low-stock alerts
* CSV import/export
* barcode scanner compatibility
* backup utility
* simple reporting

***

# 12. Packaging and Setup Pitfalls

Even for non-production, installation friction matters.

## Avoid requiring operators to run commands

Bad:

```text
python app.py
```

Better eventually:

```text
InventoryApp.exe
```

For development, Python is fine.  
For operators, package it with:

```text
PyInstaller
```

Later.

***

## Keep the database file obvious

Example folder:

```text
InventoryApp/
├── InventoryApp.exe
├── data/
│   └── inventory.db
├── backups/
│   └── inventory_2026-05-21.db
└── exports/
```

Do not hide the database somewhere mysterious during early testing.

***

# 13. Backup Strategy

Do this from day one.

Simple backup behavior:

* backup on app startup
* backup before schema changes
* backup before CSV import
* keep last 20 backups

Button:

```text
Create Backup Now
```

Also add:

```text
Open Backup Folder
```

This is low effort and prevents pain.

***

# 14. CSV Import/Export

Since this is replacing Excel, CSV import/export is essential.

## Import should support

* parts
* initial inventory balances

## Export should support

* parts list
* current inventory
* transaction history
* shipments

Important: import should preview data before committing.

Workflow:

```text
Select CSV
→ Preview rows
→ Show errors
→ Import valid rows
→ Create backup first
```

Do not silently import bad data.

***

# 15. Suggested MVP Development Order

## Phase 0 — Prototype UI flow

Before deep coding, mock the screens:

1. Dashboard
2. Parts
3. Receive
4. Ship
5. Adjust
6. History

Goal:

> Can a non-technical person understand what to do in 10 seconds?

***

## Phase 1 — Database and part management

Build:

* SQLite database
* parts table
* locations table
* add/edit part
* search part

***

## Phase 2 — Inventory transactions

Build:

* receive stock
* ship stock
* adjust stock
* update balances
* transaction history

This is the real core.

***

## Phase 3 — Low-friction operator features

Build:

* autocomplete
* recent parts
* default location
* clear success messages
* helpful error messages

***

## Phase 4 — Shipping records

Build:

* shipment number
* recipient/reference
* carrier/tracking fields
* shipment history

***

## Phase 5 — CSV and backup

Build:

* CSV import
* CSV export
* automatic backup

***

# 16. Recommended UI Style

Use a modern, minimal desktop style.

## Layout

Left sidebar:

```text
Dashboard
Parts
Receive
Ship
Move / Adjust
History
Settings
```

Top area:

```text
Search bar
Operator name
```

Main area:

```text
Task-focused screen
```

***

## Visual design

Use:

* lots of whitespace
* clear cards
* large buttons
* consistent icons
* plain language
* minimal colors
* readable fonts
* no dense spreadsheet grids unless needed

For operators, the app should feel more like a kiosk/task app than a database editor.

***

# 17. ADHD-Friendly Defaults

I would explicitly design these in:

## Quick actions

On dashboard:

```text
Receive Stock
Ship Stock
Find Part
```

Big buttons.

***

## Smart defaults

Remember:

* last operator
* last location
* last transaction type
* recent parts

***

## Gentle guardrails

Examples:

```text
Quantity must be greater than zero.
```

```text
This shipment would leave only 1 item in stock.
Minimum is 5.
Continue?
```

***

## Completion feedback

After every action:

```text
Done — 8 units received.
Current stock: 23.
```

This matters. The user should never wonder if the action worked.

***

## No hidden state

If a filter is active, show it clearly.

Example:

```text
Showing: Low stock only
Clear filter
```

***

# 18. My Revised Recommendation

Build this as a **simple local inventory control app**, not a full ERP yet.

## Name it internally something like:

```text
Inventory Control MVP
```

not:

```text
ERP System
```

That prevents scope creep.

***

# Final MVP Feature List

## Must-have

* part database
* location database
* current stock by location
* receive stock
* ship stock
* adjust stock
* move stock
* transaction history
* low-stock alerts
* search
* CSV export
* automatic backups

## Should-have

* CSV import
* barcode scanner input
* shipment tracking number
* operator name
* recent activity
* inactive parts
* simple dashboard

## Not yet

* accounting
* purchase orders
* sales orders
* customer CRM
* supplier management
* role-based permissions
* cloud sync
* carrier integrations
* serial/lot tracking
* complex reports

***

# Best Next Step

Before writing full code, I’d define the **first three workflows in detail**:

1. **Receive stock**
2. **Ship stock**
3. **Correct stock count**

If those three are smooth, the whole app will feel useful quickly.

A good next design artifact would be a short workflow spec like:

```text
Screen: Ship Stock
User goal: Reduce stock and record shipment.
Required inputs:
- part
- quantity
- location
- recipient/reference
Optional:
- carrier
- tracking number
- notes
Validation:
- quantity > 0
- enough stock available
Output:
- shipment record
- inventory transaction
- updated balance
- success confirmation
```

That level of planning is enough to start coding without overengineering.
