# GUIDANCE.md

## InvSys Front-End Modernization Guidance

> **Status clarification (2026-10-02):** This guidance was captured with the approved
> Phase 0 prototype and is being added to `main` after the first production desktop
> slice landed. Its phase sequence describes the migration plan; the progress table
> below records current delivered scope, including partial phases. Consult
> [desktop scope and validation](docs/frontend/desktop.md), current code and tests,
> and merged PRs for delivered behavior. The
> [approved design decisions](docs/frontend/phase0-design.md) remain the visual reference.

This document defines the architectural direction, implementation sequence, design goals, constraints, quality gates, and agent operating rules for the InvSys front-end modernization project.

It is intentionally more prescriptive than a normal roadmap.

Agents working on InvSys should use this document to answer:

- What are we building?
- Why are we building it this way?
- What belongs in Python versus the frontend?
- What may be changed?
- What must not be changed?
- Which phase are we currently working on?
- What does "done" mean for that phase?
- What should be tested before progressing?
- What architectural mistakes should be avoided?

The goal is not merely to replace PySide6.

The goal is to evolve InvSys into a polished, local-first inventory workstation while preserving the reliable Python inventory engine already built.

---

# 1. Project North Star

InvSys should feel like a modern inventory command center while remaining:

- local-first
- offline-capable
- fast
- understandable
- recoverable
- auditable
- difficult to misuse
- easy to maintain
- easy for coding agents to reason about

The product philosophy remains:

> Make the correct action obvious, make mistakes hard, and make recovery easy.

The visual redesign must not compromise inventory correctness.

The desired result is:

```text
Python inventory engine
        +
SQLite / SQLAlchemy
        +
explicit application bridge
        +
pywebview desktop shell
        +
HTML / CSS / TypeScript frontend
        +
modern glassmorphic design system
        +
high-quality data visualization
        =
polished local-first inventory workstation
```

---

# 2. Source of Truth and Documentation Precedence

Some older repository documentation may describe architecture that has already changed.

For example, older documentation may refer to:

- an in-memory `InventoryStore`
- SQLAlchemy as planned rather than implemented
- earlier UI structures
- older MVP assumptions

Agents MUST NOT blindly trust stale prose.

Use this precedence when information conflicts:

```text
1. Current automated tests
2. Current executable code
3. Current database / ORM implementation
4. Current README.md
5. GUIDANCE.md
6. ROADMAP.md / DIRECTION.md
7. CLAUDE.md or older architecture notes
```

`GUIDANCE.md` is authoritative for the front-end modernization strategy.

However, it does not override working business rules encoded in current code and tests.

If documentation conflicts with tested behavior:

> preserve tested behavior unless the task explicitly requires changing it.

Agents should update stale documentation when encountered if doing so is safely within the task scope.

Do not resurrect previously replaced architecture simply because an older document mentions it.

---

# 3. Core Migration Principle

This is a:

> front-end replacement

It is NOT a:

> complete InvSys rewrite

The existing Python domain and persistence layers contain valuable working behavior.

Preserve them.

The migration should resemble:

```text
CURRENT

PySide6 UI
    ↓
InventoryStore / application logic
    ↓
SQLAlchemy
    ↓
SQLite
```

transitioning toward:

```text
TARGET

HTML / CSS / TypeScript
          ↓
typed frontend bridge
          ↓
Python application API
          ↓
existing domain / service logic
          ↓
SQLAlchemy
          ↓
SQLite
```

The frontend is replaceable.

Inventory correctness is not.

---

# 4. Architectural Boundaries

## 4.1 Python Owns Business Truth

Python remains authoritative for:

- inventory validation
- inventory balances
- transactions
- shipment creation
- lot tracking
- BOM explosion
- BOM availability
- BOM allocation
- BOM shipment validation
- move operations
- adjustments
- stock availability
- low-stock determination
- import/export rules
- backups
- settings persistence
- database writes
- transaction atomicity
- domain validation

JavaScript must never become the authoritative implementation of inventory rules.

---

# 5. Frontend Responsibilities

The frontend owns:

- presentation
- navigation
- interaction state
- forms
- animations
- drawers
- dialogs
- tables
- filters
- client-side display formatting
- frontend accessibility
- theme management
- loading states
- optimistic visual previews where safe
- graph rendering
- command palette interaction
- local component state

The frontend MAY calculate temporary visual previews.

Example:

```text
Current stock: 100
Shipping: 20
Preview remaining: 80
```

But Python must still validate the actual operation when submitted.

Python wins if frontend assumptions and backend state disagree.

---

# 6. Database Access Rule

Frontend code MUST NEVER:

- access SQLite directly
- contain SQL
- modify ORM models
- write database files
- emulate database transactions
- assume database internals

Only Python application/domain code accesses persistence.

Correct:

```text
Frontend
→ bridge.ship_stock(...)
→ Python
→ domain validation
→ database transaction
```

Incorrect:

```text
Frontend
→ SQLite
```

---

# 7. Bridge Architecture

Do not expose the complete `InventoryStore` object directly to JavaScript.

Create an intentional bridge.

Suggested structure:

```text
inventory_control/
├── api/
│   ├── __init__.py
│   ├── bridge.py
│   ├── serializers.py
│   └── responses.py
│
├── webview/
│   ├── __init__.py
│   └── window.py
│
├── store.py
├── models.py
├── orm.py
└── ...
```

The bridge should expose use cases, not Python internals.

Examples:

```text
get_dashboard()
search_parts()
get_part()
create_part()
update_part()

receive_stock()
ship_stock()
preview_shipment()

move_stock()
adjust_stock()

get_bom_tree()
get_bom_availability()
preview_bom_shipment()

get_transactions()

preview_import()
commit_import()
export_data()

get_settings()
update_settings()
create_backup()
```

Avoid bridge methods such as:

```text
execute_query()
get_model()
set_balance()
update_database_row()
```

Those leak persistence implementation into the UI.

---

# 8. Bridge Response Contract

All bridge operations should eventually return predictable JSON-safe structures.

Success:

```json
{
  "ok": true,
  "data": {
    "part_number": "MAT-004",
    "new_quantity": 1490
  }
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "Only 42 units are available.",
    "details": {
      "available": 42,
      "requested": 50
    }
  }
}
```

Expected domain validation errors should not surface as raw stack traces in the user interface.

Unexpected exceptions should:

1. be logged
2. be converted to a safe frontend error
3. retain enough context for debugging
4. never expose raw technical noise to normal operators

---

# 9. Proposed Frontend Stack

Preferred starting stack:

```text
Desktop shell       pywebview
Build tooling       Vite
Language            TypeScript
Markup              HTML
Styling             CSS
Icons               Lucide
BOM graph           Cytoscape.js
Python tests        pytest
Frontend tests      Vitest
E2E later           Playwright
Packaging           PyInstaller
```

Do not introduce React initially unless frontend complexity demonstrates a clear need.

Do not introduce Redux.

Do not introduce a large UI framework unless there is a concrete benefit.

Prefer:

> small, explicit, understandable modules

over:

> framework complexity for its own sake

---

# 10. Desired Repository Structure

Target direction:

```text
InvSys/
├── inventory_control/
│   ├── api/
│   │   ├── bridge.py
│   │   ├── serializers.py
│   │   └── responses.py
│   │
│   ├── webview/
│   │   └── window.py
│   │
│   ├── store.py
│   ├── models.py
│   ├── orm.py
│   ├── backup.py
│   ├── import_export.py
│   └── ...
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   │
│   └── src/
│       ├── main.ts
│       ├── app.ts
│       │
│       ├── api/
│       │   ├── bridge.ts
│       │   └── types.ts
│       │
│       ├── components/
│       │   ├── sidebar.ts
│       │   ├── header.ts
│       │   ├── data-table.ts
│       │   ├── drawer.ts
│       │   ├── modal.ts
│       │   ├── toast.ts
│       │   ├── command-palette.ts
│       │   └── status-badge.ts
│       │
│       ├── pages/
│       │   ├── dashboard/
│       │   ├── parts/
│       │   ├── bom/
│       │   ├── receive/
│       │   ├── ship/
│       │   ├── move/
│       │   ├── adjust/
│       │   ├── history/
│       │   └── settings/
│       │
│       ├── styles/
│       │   ├── tokens.css
│       │   ├── global.css
│       │   ├── glass.css
│       │   ├── animations.css
│       │   └── components/
│       │
│       └── utils/
│
├── tests/
│   ├── ...
│   └── bridge/
│
└── frontend/tests/
```

This is a direction, not an excuse to perform a giant repository reshuffle immediately.

Refactor incrementally.

---

# 11. Visual Design Direction

The design language is:

> Glassmorphic Admin

But usability and data readability take precedence over visual effects.

## Dark Theme

Base:

```text
#0f172a
```

Primary text:

```text
#f8fafc
```

Secondary:

```text
#94a3b8
```

Primary accent:

```text
Indigo #6366f1
→
Cyan #06b6d4
```

Success:

```text
#10b981
```

Danger / critical:

```text
#f43f5e
```

---

# 12. Glass Usage Rule

Glass should frame information, not obscure it.

Use stronger glass effects on:

- sidebar
- top navigation
- dashboard cards
- dialogs
- drawers
- floating controls
- selected inspectors

Use more opaque surfaces for:

- inventory tables
- transaction history
- CSV previews
- long forms
- data-dense views

Avoid turning every element into translucent glass.

Data readability is more important than aesthetic consistency.

---

# 13. Design Tokens

Do not scatter magic colors and values throughout components.

Create centralized tokens.

Examples:

```css
--bg-primary
--bg-secondary

--surface-1
--surface-2
--surface-glass

--border-subtle
--border-active

--text-primary
--text-secondary
--text-muted

--accent-indigo
--accent-cyan

--success
--warning
--danger
--info

--radius-sm
--radius-md
--radius-lg

--space-1
--space-2
--space-3
--space-4
--space-5
--space-6
--space-7
--space-8
```

Dark and light themes should mostly swap token values rather than duplicate component CSS.

---

# 14. Layout Rules

Desktop-first layout.

Primary structure:

```text
250px sidebar
+
flexible content area
```

Use an 8px spacing grid.

Typical main content padding:

```text
32px
```

Panel radius:

```text
12px
```

Maintain generous whitespace.

Avoid unnecessarily dense controls.

---

# 15. Navigation Target

Prefer direct navigation over nested navigation where practical.

Target sidebar:

```text
INVSYS
Inventory Control

Dashboard

INVENTORY
Parts
BOM

OPERATIONS
Receive
Ship
Move
Adjust

RECORDS
History

Settings
Theme
```

An operator should normally reach a workflow with one navigation action.

---

# 16. Keyboard Navigation

Preserve and improve keyboard-first workflows.

Expected baseline:

```text
Ctrl+K    Global search / command palette

Ctrl+1    Dashboard
Ctrl+2    Parts
Ctrl+3    BOM
Ctrl+4    Receive
Ctrl+5    Ship
Ctrl+6    Move
Ctrl+7    Adjust
Ctrl+8    History
```

Keyboard navigation must not become worse than the current application.

---

# 17. Motion Principles

Motion should communicate state.

It should not exist merely as decoration.

Suggested timing tokens:

```text
instant     100ms
fast        160ms
normal      220ms
slow        300ms
```

Suggested easing:

```text
cubic-bezier(.2,.8,.2,1)
```

Typical usage:

```text
Navigation          160ms
Drawer              220ms
Modal               180ms
Toast               220ms
Button hover        120ms
Card hover          160ms
Table hover         100ms
Theme transition    300ms
BOM transitions     250-400ms
```

Prefer:

```text
translateY(-2px)
```

over aggressively scaling large dashboard cards.

Respect:

```css
@media (prefers-reduced-motion: reduce)
```

from the beginning.

---

# 18. Accessibility and Low-Friction UX

The application should remain usable by:

- mouse
- keyboard
- touchscreen-like interaction where practical

Always provide:

- visible focus states
- persistent field labels
- meaningful button labels
- status text in addition to color
- clear validation messages
- appropriate contrast
- understandable language

Never use color alone to communicate inventory health.

Example:

```text
● Low stock
```

not merely:

```text
red dot
```

---

# 19. Agent Working Rules

Every coding agent should follow these rules.

## Before Editing

1. Inspect the relevant current code.
2. Inspect relevant tests.
3. Identify the current migration phase.
4. Determine whether the requested work belongs to that phase.
5. Check for existing reusable components before creating new ones.
6. Understand the Python/frontend boundary involved.
7. Check current Git status and branch context.
8. Follow repository Git identity requirements defined by project-level agent instructions.

Do not start large modifications based only on documentation summaries.

---

# 20. Scope Discipline

Agents should complete the smallest coherent change that advances the active phase.

Do not combine unrelated work such as:

```text
"Implement dashboard"
+
"refactor ORM"
+
"rewrite import system"
+
"rename half the repository"
```

unless explicitly instructed.

Prefer:

> one coherent capability per branch / PR

where practical.

---

# 21. Preserve Existing Behavior

A visual rewrite is not authorization to change business behavior.

For each migrated workflow, first identify existing behavior.

Example:

```text
Ship stock
```

must preserve:

- lot rules
- available quantity validation
- transaction creation
- shipment creation
- BOM behavior where applicable
- operator recording
- atomicity
- error conditions

Only presentation should change unless a behavioral change is explicitly requested.

---

# 22. Never Duplicate Domain Logic

If Python already answers a question, use Python.

Bad:

```typescript
if (requestedQuantity > currentStock) {
    throw ...
}
```

as the final authority.

Acceptable:

```typescript
// Visual preview only
const appearsValid = requestedQuantity <= displayedStock;
```

Final submission still goes to Python validation.

---

# 23. No Silent Behavior Changes

If implementing a frontend requires changing Python behavior:

STOP and make that change explicit.

Document:

- current behavior
- desired behavior
- reason
- affected tests
- migration impact

Do not hide business-rule modifications inside UI PRs.

---

# 24. Testing Rule

Existing tests are a safety net, not optional cleanup.

Before completing work:

```text
relevant existing tests pass
+
new behavior has appropriate tests
+
no known regression is hidden
```

If an existing test must change, explain why behavior intentionally changed.

Do not delete failing tests simply to make CI green.

---

# 25. Migration Strategy

Migration must be vertical and incremental.

Do NOT:

1. rewrite every screen
2. remove PySide6
3. hope everything works afterward

Instead:

```text
build new capability
→ validate it
→ migrate one workflow
→ compare behavior
→ proceed
```

PySide6 should remain usable until the replacement reaches sufficient feature parity.

---

# 26. Phase 0: Static Visual Prototype

## Goal

Define what modern InvSys looks and feels like before introducing bridge complexity.

## Build

Create a standalone frontend using realistic fake inventory data.

Required prototype views:

- application shell
- sidebar
- top header
- dashboard
- parts table
- part detail drawer
- receive stock
- ship stock
- BOM explorer shell
- history
- theme switching

## Include

- design tokens
- dark mode
- light mode
- glass surfaces
- table styling
- status badges
- buttons
- form controls
- toast design
- drawer
- modal
- navigation
- basic transitions

## Do NOT

- integrate SQLite
- integrate pywebview
- call Python
- modify inventory behavior
- refactor `InventoryStore`
- remove PySide6
- build production bridge logic

## Focus

Answer:

> Does this feel like InvSys?

before answering:

> Can this call Python?

## Expected Result

The prototype should be navigable and visually representative enough that future agents can implement against a stable design language.

## Exit Criteria

Phase 0 is complete when:

- primary pages exist visually
- dark/light themes work
- sidebar/navigation works
- reusable components are identified
- fake inventory data looks realistic
- layout works at expected desktop resolutions
- no Python backend integration is required to demonstrate the intended experience

---

# 27. Phase 1: pywebview and Bridge Proof of Concept

## Goal

Prove that the architecture works before migrating real workflows.

## Build

Introduce:

```text
pywebview
frontend build output
Python bridge
basic typed frontend wrapper
```

Create a diagnostics screen or temporary development panel.

Test:

```text
JS → Python
Python → JS
Python → JSON data
validation error → frontend
frontend → Python mutation
packaged frontend loading
```

## Suggested Diagnostic Information

```text
Python version
Database status
Database path
Parts count
Locations count
Frontend version
Bridge health
```

## Do NOT

- migrate complex screens yet
- expose raw `STORE`
- expose arbitrary Python execution
- implement generic database query endpoints
- remove old application entry point

## Expected Result

A pywebview window can reliably load the Vite frontend and communicate with Python through a narrow explicit API.

## Exit Criteria

- pywebview launches consistently
- production frontend assets can load
- bridge calls return typed data
- domain errors can be displayed safely
- unexpected errors are logged
- basic packaging strategy has been validated
- existing pytest suite remains healthy

---

# 28. Phase 2: Dashboard Migration

## Goal

Migrate the first real screen using mostly read-only data.

Dashboard is intentionally first because its risk to inventory state is low.

## Python

Provide a purpose-built endpoint such as:

```text
get_dashboard()
```

Potential response:

```json
{
  "stats": {},
  "low_stock": [],
  "recent_activity": [],
  "recent_shipments": []
}
```

Prefer one cohesive dashboard response over many tiny bridge calls.

## Frontend

Implement:

- summary cards
- low-stock attention panel
- recent activity
- recent shipments
- quick actions
- loading state
- error state
- empty state

Dashboard widgets should be actionable.

Examples:

```text
click Low Stock
→ Parts filtered by low stock

click shipment
→ History filtered to shipment

click part
→ open part detail
```

## Do NOT

- turn dashboard cards into decorative dead ends
- create domain logic for stock health in TypeScript
- query every statistic independently unless necessary

## Expected Result

The new frontend displays live inventory state while remaining read-only enough to be low risk.

## Exit Criteria

- dashboard matches Python state
- loading/errors are handled
- quick navigation works
- low-stock links are meaningful
- theme works
- keyboard navigation works
- no database writes occur from dashboard presentation code

---

# 29. Phase 3: Parts Workspace

## Goal

Build the core reusable data-management experience.

This phase establishes many components used elsewhere.

## Build

Parts page with:

- search
- sorting
- filters
- active/inactive status
- low-stock status
- inventory totals
- locations where useful
- part creation
- part editing
- part detail drawer

## Detail Drawer

The drawer should preserve list context.

Suggested content:

```text
Part number
Description
Revision
Category
Status

Total stock
Minimum quantity
Locations

Recent activity

Receive
Ship
Move
History
Edit
```

## Important Components Created Here

- data table
- filters
- search
- drawer
- form validation
- dialog
- confirmation flow
- toast
- status badge
- empty state
- skeleton/loading state

These should become shared primitives.

## Do NOT

- navigate away unnecessarily just to inspect a part
- duplicate tables for each page if a generic table component works
- expose raw ORM fields just because they exist

## Expected Result

Parts becomes a polished power-user workspace and creates a reusable component foundation for later phases.

## Exit Criteria

- searching works
- filtering works
- sorting works
- create/edit behavior matches Python rules
- active/inactive behavior is preserved
- drawer works
- navigation to related workflows works
- required domain validation still occurs in Python
- tests cover bridge operations

---

# 30. Phase 4: History Migration

## Goal

Prove the new frontend can handle large, filterable datasets.

## Build

History view supporting filters such as:

- search
- part
- transaction type
- operator
- reference
- date range
- shipment
- location where useful

## Backend Strategy

Avoid permanently shipping unlimited transaction history to JavaScript.

Prefer pagination or bounded queries.

Example:

```text
get_transactions({
    page,
    page_size,
    search,
    type,
    from_date,
    to_date
})
```

## Frontend

Include:

- visible active filters
- clear filters action
- pagination or virtualized approach if required
- timestamp formatting
- transaction badges
- detail inspection

## Expected Result

The frontend demonstrates scalable data querying rather than treating the database as a small static array.

## Exit Criteria

- large transaction datasets remain responsive
- filters are explicit
- queries are handled by Python
- frontend does not load unnecessary history
- history matches database records
- no audit information is lost or hidden

---

# 31. Phase 5: Receive Stock Migration

## Goal

Migrate the first important inventory mutation.

## UX Model

Receive should behave like a guided transaction.

Suggested flow:

```text
1. Select item
2. Enter receipt details
3. Review resulting stock
4. Submit
5. Confirm success
```

## Required Inputs

Respect current domain rules, including lot tracking.

Likely information includes:

```text
Part
Quantity
Lot
Location
Reference
Operator
Notes
```

Do not rely on old documentation if current code requires additional fields.

## Review

Show:

```text
Current stock
Receiving amount
Expected resulting stock
```

This is a preview.

Python remains authoritative.

## Success Feedback

Avoid:

```text
Saved.
```

Prefer:

```text
250 units received into Stock.
New quantity: 1,490.
```

## Expected Result

The user can safely receive inventory using the new frontend with behavior equivalent to the existing application.

## Exit Criteria

- receive uses Python domain logic
- lot validation remains intact
- inventory balances update correctly
- transaction history updates
- relevant UI data refreshes
- duplicate submission is guarded against
- clear success/error feedback exists
- regression tests pass

---

# 32. Phase 6: Move and Adjust Migration

## Goal

Migrate inventory correction and relocation workflows.

These should be separate user experiences even if they share internal components.

---

## Move

Display:

```text
Part
Lot
Source
Destination
Quantity
```

Preview:

```text
Rack A
100 → 80

Rack B
20 → 40
```

Python must preserve atomic:

```text
MOVE_OUT
+
MOVE_IN
```

behavior.

Neither side may succeed independently.

---

## Adjust

Display:

```text
Part
Lot
Location
Expected quantity
Counted quantity
Difference
Reason
```

Difference can be calculated visually.

Python creates authoritative adjustment transactions.

Reason must remain required where domain rules require it.

## Expected Result

The new UI makes physical inventory corrections easier to understand than the old generic form approach.

## Exit Criteria

- moves remain atomic
- no negative stock regression
- lot behavior remains correct
- adjustment reason behavior remains correct
- transaction records match old behavior
- resulting balances are correctly refreshed
- frontend clearly differentiates move vs adjust

---

# 33. Phase 7: Ship Stock and BOM Shipment Migration

## Goal

Migrate the highest-risk everyday inventory workflow.

Proceed only after Receive, Move, and Adjust have proven the mutation architecture.

## Standard Shipping

Suggested review:

```text
Current stock     250
Shipping          180
Remaining          70
```

Warn when resulting stock crosses a meaningful threshold.

Do not prevent an otherwise valid shipment merely because it becomes low stock unless current business rules require blocking it.

## Python Responsibilities

Python validates:

- part
- lot
- location
- quantity
- stock availability
- shipment data
- transaction creation
- shipment creation

---

## BOM Shipping

Preserve all existing rules.

Current behavior includes important concepts such as:

- recursive BOM explosion
- leaf-component consumption
- lot allocation
- allocation review
- availability validation
- all-or-nothing behavior
- shipment traceability

Do NOT simplify BOM shipping merely because frontend implementation becomes more difficult.

## Allocation Review

If current Python requires reviewing lot allocations before execution, preserve it.

Suggested UX:

```text
Assembly: ASM-100
Quantity: 10

COMPONENT       REQUIRED     LOT       AVAILABLE
MOTOR-1         10           LOT-A     24
SCREW-4         40           LOT-B     100
PCB-2           10           LOT-C     18

[Confirm shipment]
```

If allocation changes between review and submission:

- Python rejects stale review
- frontend refreshes
- user reviews updated allocation

## Expected Result

The modern frontend achieves feature parity with the most important existing shipment behavior without moving business rules into TypeScript.

## Exit Criteria

- normal shipments work
- BOM shipments work
- lot allocations work
- stale allocation review is handled
- insufficient stock is handled
- no partial BOM transaction state exists
- shipment traceability remains intact
- all existing relevant tests pass
- new bridge tests cover shipping scenarios

---

# 34. Phase 8: Interactive BOM Explorer

## Goal

Turn BOM visualization into one of InvSys's defining features.

This is primarily a presentation enhancement.

Python remains responsible for calculating graph truth.

## Technology

Prefer Cytoscape.js unless another library demonstrates a concrete technical advantage.

## Features

Target:

- nested BOM visualization
- drag canvas
- zoom
- fit-to-screen
- click node
- inspector panel
- collapse/expand subtree
- focus subtree
- breadcrumbs
- build quantity input
- required quantities
- available quantities
- buildable quantity
- low/critical status
- shortage propagation
- smooth graph transitions

## Example

```text
                ASM-100
              Buildable 126
                   │
          ┌────────┴────────┐
          │                 │
       MOTOR-4           PCB-210
        x1                x1
        ●184              ●129
          │
      ┌───┴────┐
      │        │
   SHAFT-2  BEARING-5
    x1         x2
    ●920      LOW 252
```

## Inspector

Selecting a node can expose:

```text
Part
Description
Required
Available
Remaining
Build capacity
Locations
Status

View Part
View History
```

## Do NOT

- calculate canonical BOM structure in JavaScript
- calculate shipment allocation in JavaScript
- allow graph interaction to mutate inventory directly

## Expected Result

InvSys gains a highly polished interactive BOM visualization while preserving existing domain logic.

## Exit Criteria

- complex nested BOMs render correctly
- graph matches Python BOM output
- shortages are clear
- selected nodes provide useful context
- navigation back to parts/history works
- large BOMs remain acceptably responsive
- motion does not obscure information

---

# 35. Phase 9: Global Command Search

## Goal

Transform existing global search into an application-wide productivity tool.

Trigger:

```text
Ctrl+K
```

## Search Targets

Potential targets:

```text
parts
shipments
references
locations
actions
recent items
```

Example:

```text
Search InvSys...

PARTS
MAT-104 · Stainless Screw

ACTIONS
Receive MAT-104
Ship MAT-104
Move MAT-104
View MAT-104 history

RECENT
SHP-20260929-0004
```

## Design Goal

Experienced operators should eventually be able to navigate InvSys largely from the keyboard.

## Do NOT

turn this into an enormous omniscient search engine in the first implementation.

Start with high-value actions.

## Exit Criteria

- Ctrl+K works globally
- keyboard selection works
- Escape closes
- Enter activates
- search results are useful
- part actions navigate correctly
- focus behavior is predictable

---

# 36. Phase 10: Settings, Import/Export and Backup

## Goal

Migrate operational support capabilities after core inventory workflows are stable.

## Settings

Include only meaningful settings.

Do not create a settings page full of cosmetic configuration merely because it is easy.

Potential settings:

```text
Theme
Operator
Default/recent preferences
Backup information
Application diagnostics
```

## Import

Preserve safety workflow:

```text
Select file
→ preview
→ validate
→ show row errors
→ backup
→ commit
```

Never silently import malformed inventory data.

## Export

Keep export actions straightforward.

Potential exports:

```text
parts
inventory
transactions
shipments
BOM definitions
```

## Backup

Support:

```text
Create backup
Open backup location
Show latest backup
```

## Expected Result

All operational utilities work in the modern frontend without bypassing the Python implementations.

## Exit Criteria

- imports preview before commit
- validation errors remain visible
- backup happens where required
- exports match Python data
- no frontend direct filesystem assumptions leak across platforms

---

# 37. Phase 11: PySide6 Retirement

## Goal

Remove the old presentation layer only after the new application has sufficient feature parity.

This is intentionally late.

## Before Removal

Create a migration checklist comparing:

```text
Dashboard
Parts
BOM
Receive
Ship
Move
Adjust
History
Settings
Import/export
Backup
Keyboard shortcuts
Lot behavior
BOM allocation
```

Every required capability should be classified:

```text
Equivalent
Improved
Intentionally changed
Not required
Missing
```

No important workflow may be silently omitted.

## Remove

Only after verification:

- old PySide6 views
- old widgets
- old QSS
- unused UI dependencies
- obsolete launch code

Do not remove Python dependencies that are still used elsewhere merely because they were historically UI-related.

## Expected Result

InvSys becomes a pywebview application rather than a dual-UI project.

## Exit Criteria

- new frontend reaches agreed feature parity
- old UI provides no required unique capability
- tests pass
- application launches entirely through new shell
- packaging works
- documentation reflects actual architecture

---

# 38. Phase 12: Hardening

## Goal

Turn the successful rewrite into a dependable application.

## Performance

Test:

- large part catalogs
- large transaction history
- large BOM trees
- repeated navigation
- long-running sessions

## Accessibility

Verify:

- keyboard
- focus management
- labels
- contrast
- reduced motion
- screen-reader-friendly semantics where practical

## Reliability

Test:

- invalid input
- database errors
- missing files
- failed import
- corrupted user input
- bridge errors
- stale frontend state
- duplicate submission

## Packaging

Validate packaged application behavior.

Do not assume a frontend that works in Vite dev mode automatically works under PyInstaller.

## Expected Result

A release candidate that is visually polished and operationally boring.

"Boring" here is positive.

Inventory operations should be predictable.

---

# 39. Testing Architecture

Maintain existing Python tests.

Add bridge tests independently from pywebview where possible.

Suggested:

```text
tests/
├── existing domain tests
│
└── bridge/
    ├── test_dashboard_api.py
    ├── test_parts_api.py
    ├── test_inventory_api.py
    ├── test_shipping_api.py
    ├── test_bom_api.py
    └── test_serialization.py
```

Frontend:

```text
frontend/tests/
├── navigation.test.ts
├── table.test.ts
├── forms.test.ts
├── validation.test.ts
├── drawer.test.ts
└── command-palette.test.ts
```

Later add E2E flows.

Example:

```text
Create part
→ receive stock
→ verify stock
→ move stock
→ verify locations
→ ship stock
→ verify remaining quantity
→ inspect history
```

Also:

```text
Create BOM
→ receive leaf components
→ preview BOM shipment
→ confirm allocation
→ ship parent
→ verify component consumption
→ verify shipment trace
```

---

# 40. Definition of Done for a Migrated Screen

A screen is not done because it looks correct.

It is done when:

- visual design is implemented
- loading state exists
- empty state exists
- error state exists
- keyboard behavior works
- relevant domain behavior matches Python
- bridge is typed
- expected validation works
- unexpected errors are safe
- relevant tests pass
- duplicate components were not unnecessarily created
- old behavior was compared
- accessibility basics are present
- documentation is updated if architecture changed

---

# 41. Definition of Done for a PR

Before requesting merge, the agent should report:

## What changed

Short description.

## Why

Which phase goal it advances.

## Architecture

What boundaries were introduced or affected.

## Tests

Exactly what was run.

## Manual verification

What workflow was manually exercised.

## Known limitations

Anything intentionally deferred.

## Follow-up

What logical next step remains.

Avoid PR descriptions such as:

```text
Updated UI.
```

Prefer:

```text
Migrates the Dashboard to the pywebview frontend using the new read-only dashboard bridge. Adds reusable StatCard and ActivityList components. No inventory mutation behavior changed.
```

---

# 42. Agent Stop Conditions

An agent should stop and report rather than improvising if it discovers:

- required existing behavior is unclear
- tests contradict documentation
- database migration appears necessary
- domain behavior would need to change
- existing data could be lost
- packaging strategy fundamentally fails
- pywebview cannot support a required capability
- another active change modifies the same architectural boundary
- a requested action would bypass inventory safeguards

This does NOT mean agents should stop for ordinary implementation decisions.

Use judgment.

Small local decisions should be made autonomously.

Architectural/domain changes deserve visibility.

---

# 43. Multiple-Agent Coordination

The migration is designed to support multiple agents.

Prefer parallel work across isolated boundaries such as:

```text
Agent A
Design system

Agent B
Python bridge DTOs

Agent C
Dashboard components

Agent D
Bridge tests
```

Avoid parallel agents simultaneously rewriting:

```text
bridge.py
app.ts
shared API types
```

without coordination.

When multiple worktrees are used:

- keep tasks narrow
- keep commits focused
- communicate dependencies
- merge foundational changes before dependent changes where practical

Do not have three agents independently invent three API conventions.

---

# 44. Shared Components Before Duplication

Before creating a component, search for an existing implementation.

Common shared candidates include:

```text
Button
Input
Select
Search
Card
Panel
DataTable
Badge
Toast
Modal
Drawer
Tooltip
EmptyState
LoadingState
FormField
ConfirmationDialog
```

Avoid abstracting every two-line HTML fragment.

Create abstractions when reuse or consistency justifies them.

---

# 45. TypeScript Standards

Use strict TypeScript.

Prefer:

```text
explicit exported types
discriminated unions for important states
typed bridge methods
typed API responses
```

Avoid widespread:

```typescript
any
```

Do not reproduce Python ORM models blindly as frontend types.

Create frontend-facing DTOs around actual UI needs.

---

# 46. State Management

Start simple.

Prefer:

- page-local state
- small shared application state
- explicit invalidation/refetch

Do not introduce global state frameworks prematurely.

A successful mutation should explicitly refresh affected data.

Example:

```text
receiveStock()
→ success
→ refresh selected part
→ refresh dashboard summaries
→ refresh recent activity
```

A richer event model may be introduced later if actual complexity justifies it.

---

# 47. Data Freshness

Do not let visual polish introduce stale inventory state.

After mutations, affected views should refresh.

Important affected areas may include:

```text
Dashboard
Parts
Part drawer
History
BOM availability
Shipment previews
```

Existing subscriber behavior demonstrates that stale data is already considered a serious failure mode.

Preserve that mindset.

---

# 48. Error Language

Users should see human language.

Bad:

```text
ValueError: No balance row found for...
```

Good:

```text
There is not enough stock in this location.
Available: 4
Requested: 10
```

Technical detail belongs in logs.

---

# 49. Destructive and Sensitive Actions

Require clear confirmation for actions with significant consequences.

Examples:

- unusual adjustment
- deactivating important records
- import commit
- backup restore when added
- shipment with unusual consequences where appropriate

Do not interrupt routine workflows with unnecessary confirmations.

Guardrails should reduce errors without creating confirmation fatigue.

---

# 50. Product Principles for Every Design Decision

When uncertain, optimize in this order:

1. Inventory correctness
2. Traceability
3. Clear operator understanding
4. Low friction
5. Accessibility
6. Performance
7. Visual polish
8. Cleverness

Never reverse this ordering just to create a prettier interface.

---

# 51. What Agents Should Strive For

The application should increasingly feel:

```text
fast
calm
intentional
clear
responsive
modern
trustworthy
```

Not:

```text
busy
flashy
fragile
overanimated
framework-heavy
spreadsheet-like
```

---

# 52. What Agents Must Avoid

Do not:

- rewrite working Python business logic without need
- duplicate inventory rules in TypeScript
- access SQLite from JavaScript
- expose raw database operations through the bridge
- remove PySide6 prematurely
- introduce a localhost web server without a strong reason
- introduce FastAPI merely because the frontend uses HTML
- migrate to Electron
- add React automatically
- add Redux automatically
- introduce a large CSS framework by default
- make every surface transparent
- overuse blur
- overuse gradients
- animate routine actions excessively
- sacrifice text contrast
- hide active filters
- hide errors
- silently alter transactions
- hard-delete inventory history
- allow negative stock if existing rules prohibit it
- bypass lot requirements
- weaken BOM shipment validation
- remove tests to silence regressions
- combine unrelated refactors into migration work
- turn InvSys into a full ERP

---

# 53. Out of Scope Unless Explicitly Requested

The frontend rewrite does NOT authorize implementation of:

- accounting
- purchasing
- sales orders
- customer CRM
- supplier ERP functionality
- cloud synchronization
- authentication system
- role-based permissions
- carrier integrations
- label printing
- multi-company support
- complex analytics platform
- public REST API
- server deployment architecture

These can be reconsidered after the modernization.

---

# 54. Recommended Phase Sequence

Use this as the default migration order:

```text
Phase 0
Static design prototype
        ↓
Phase 1
pywebview + bridge proof
        ↓
Phase 2
Dashboard
        ↓
Phase 3
Parts
        ↓
Phase 4
History
        ↓
Phase 5
Receive
        ↓
Phase 6
Move + Adjust
        ↓
Phase 7
Ship + BOM shipment
        ↓
Phase 8
Interactive BOM Explorer
        ↓
Phase 9
Command Search
        ↓
Phase 10
Settings + Import/Export + Backup
        ↓
Phase 11
Retire PySide6
        ↓
Phase 12
Hardening
```

Do not skip directly from visual prototype to complete replacement.

---

# 55. Migration Progress Tracking

At the top or bottom of this document, maintain a simple status table.

Example:

| Phase | Goal | Status |
|---|---|---|
| 0 | Static visual prototype | Not Started |
| 1 | pywebview + bridge | Not Started |
| 2 | Dashboard | Not Started |
| 3 | Parts | Not Started |
| 4 | History | Not Started |
| 5 | Receive | Not Started |
| 6 | Move + Adjust | Not Started |
| 7 | Ship + BOM shipment | Not Started |
| 8 | Interactive BOM Explorer | Not Started |
| 9 | Command Search | Not Started |
| 10 | Settings / Import / Export / Backup | Not Started |
| 11 | PySide6 retirement | Not Started |
| 12 | Hardening | Not Started |

Allowed status values:

```text
Not Started
In Progress
Blocked
Review
Complete
```

Update this table when phases meaningfully change.

---

# 56. Immediate Starting Task

Unless another task is explicitly requested, the modernization effort should begin with:

> Phase 0: Static Visual Prototype

Create the modern shell and representative screens using realistic fake data.

Focus first on:

1. design tokens
2. application shell
3. sidebar
4. header/search
5. dashboard
6. parts table
7. part detail drawer
8. Receive layout
9. Ship layout
10. basic BOM Explorer layout
11. History layout
12. dark/light theme
13. motion primitives

Do not introduce Python integration during this first design pass.

The purpose of Phase 0 is to answer:

> Is this the InvSys interface we want to build?

Once the answer is yes, proceed to Phase 1.

---

# 57. Final Architectural Rule

When an implementation decision is unclear, use this question:

> Does this make InvSys easier to understand without making inventory behavior harder to trust?

If yes, it is probably aligned with the project.

If visual sophistication requires weakening correctness, traceability, maintainability, or operator understanding:

> do not make that trade.

The frontend may become dramatically more modern.

The inventory engine should remain boring, predictable, tested, and authoritative.

That combination is the goal.

---

## Migration Progress — 2026-10-02

Issues #7–#10 deliver and validate the bounded working prototype in parent #6.
Complete below means the described slice is delivered; broader phase goals remain
explicit where incomplete. See [acceptance and remaining gaps](docs/frontend/prototype-acceptance.md).

| Phase | Goal | Status |
|---|---|---|
| 0 | Static visual prototype | Complete |
| 1 | pywebview + typed bridge, local assets, basic Linux package proof | Complete |
| 2 | Live Attention first dashboard and workspace links | Complete |
| 3 | Parts search/create/details delivered; editing/deactivation deferred | In Progress |
| 4 | Searchable immutable History and persisted shipment/component trace | Complete |
| 5 | Real lot receiving, drafts, refresh, and recovery | Complete |
| 6 | Move + Adjust | Not Started |
| 7 | Standard and nested BOM review/shipment with recovery | Complete |
| 8 | Interactive BOM Explorer | Not Started |
| 9 | Part search shortcut delivered; command search deferred | In Progress |
| 10 | Operator/theme and startup backup delivered; operational utilities deferred | In Progress |
| 11 | PySide6 retirement | Not Started |
| 12 | Scripted native/keyboard/layout acceptance delivered; release hardening deferred | In Progress |

Phase 0 design decisions: `docs/frontend/phase0-design.md`.
Prototype run and review instructions: `frontend/README.md` on the preserved
`prototype/invsys-phase0` branch. The frontend on `main` is the production desktop
slice; use `docs/frontend/desktop.md` for its launch instructions and current scope.
Phase 0 is approved. Layout A (Attention first) is the selected visual reference.
