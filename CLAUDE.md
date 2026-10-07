# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running and Validating

The original PySide6 application uses Python 3.12+, PySide6, and SQLAlchemy:

```bash
pip install PySide6 SQLAlchemy
python inventory_visualizer.py
```

The optional pywebview desktop frontend uses built local assets:

```bash
pip install -r requirements-desktop.txt
npm ci --prefix frontend
npm run build --prefix frontend
python inventory_desktop.py --database /tmp/invsys-review/inventory.db
```

Omitting `--database` opens the existing operational database. For workflow smoke
checks, use an explicit disposable database; these checks perform real writes.
See `docs/frontend/desktop.md` for smoke commands, platform requirements,
packaging limits, and executed validation. See `frontend/README.md` for the live
frontend contract and `README.md` for project context.

Install test tools with `pip install -r requirements-dev.txt`. Run the automated
gate from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen python -m pytest
python -m ruff check .
npm run check --prefix frontend
npm run build --prefix frontend
```

## Current Architecture

**Inventory authority** — `inventory_control.store.InventoryStore` is the
SQLite-backed service facade. SQLAlchemy rows live in `inventory_control.orm`;
`inventory_control.models` contains detached dataclass DTOs. Store properties
return database-backed reads, not mutable in-memory inventory. Database setup
and schema bootstrap live in `db.py` and `migrations.py`.

**Original UI** — `inventory_visualizer.py` calls `inventory_control.app.main()`.
Startup backs up the database before loading the UI. The shared operational store
is initialized in `inventory_control.ui.store`. `ui/main_window.py` arranges the
views in `ui/views.py`, including BOM and Settings, with grouped Catalog and Stock
navigation. Shared widgets and Qt styling live in `ui/widgets.py` and `ui/style.py`.

**Desktop frontend** — `inventory_desktop.py` calls `inventory_control.desktop.main()`.
The launcher owns its store and exposes narrow use cases through `InventoryBridge`
in `bridge.py`. Built Vite/TypeScript assets load offline through pywebview with
no HTTP server. `frontend/src/bridge.ts` defines the typed client and DTOs;
`main.ts`, `stock.ts`, and `history.ts` handle page and workflow state.

**Existing utilities** — `backup.py` handles SQLite backups and retention;
`import_export.py` provides CSV export and validated import previews/commits.
These utilities are available through the original application's Settings view.
The optional frontend covers dashboard, Parts, Receive, standard/BOM Ship, and
History. Its deferred workflows and migration status are documented in
`docs/frontend/desktop.md`.

## Key Design Rules

- **Transaction-first inventory**: every balance change must produce a transaction record. The balance table is for fast lookup; the transaction log is the source of truth. Never subtract from a balance without a transaction row. Store mutations post stock changes through `inventory_control/ledger.py`, the only writer of balance quantities and transaction rows; nothing outside `InventoryStore` imports it.
- **No negative stock**: block shipping/moving/scrapping beyond available quantity; raise `ValueError` with a human-readable message.
- **No hard deletes**: use `active = False` on parts and locations. Never delete transaction or shipment records; instead create reversing transactions.
- **Business logic in the store/services**: views and the frontend collect input and display results. They call service methods rather than writing database rows or calculating inventory rules. Expected validation failures use human-readable `ValueError` messages. The desktop bridge validates request types and returns discriminated success/error responses; unexpected exceptions are logged and return safe messages.
- **Move creates two transaction rows**: `MOVE_OUT` from source and `MOVE_IN` to destination — both in one DB transaction so they succeed or fail together.
- **Lot traceability**: receipts require a real lot; standard shipments, moves, and adjustments act on a selected lot.
- **Phantom BOM assemblies**: nested BOM shipping consumes aggregated leaf materials only. Parent and intermediate stock stays unchanged. Allocate positive-stock lots deterministically in lot-number order using the existing store plan.
- **Reviewed, atomic BOM shipping**: shortages or changed allocations leave stock and audit records unchanged. The desktop bridge requires a matching session-local reviewed plan; changes require another explicit review and confirmation. Persist per-lot component snapshots and display them in History rather than recomputing old shipments from current BOM definitions.
- **Mutation recovery**: prevent duplicate in-flight submissions. After an ambiguous transport failure, preserve the draft and reconcile with authoritative stock/audit reads; require an explicit operator decision before resubmission.

## Testing Boundary

For desktop use cases, test the public bridge against a real temporary SQLite
database. Assert externally observable results and persistence, keeping the
existing service and Qt regressions. Strict TypeScript checking and production
builds complement the native desktop workflow and keyboard smoke checks.
No frontend test runner is installed. Report only checks actually executed.

## Transaction Types

```
RECEIVE, SHIP, SHIP_BOM, BOM_CONSUME, MOVE_OUT, MOVE_IN,
ADJUST, COUNT_CORRECTION, SCRAP, RETURN
```

## Default Locations

```
Receiving, Stock, Shipping Bench, Scrap
```

Created at first launch; do not hard-code location names in business logic — look them up from the store/DB.

## Shipment Number Format

```
SHP-YYYYMMDD-0001
```

The counter resets per day.

## Agent skills

### Issue tracker

For issue and spec workflows, use GitHub Issues in
theozex4ever/InvSys. See `docs/agents/issue-tracker.md`.

### Triage labels

For triage, use the five default labels.
See `docs/agents/triage-labels.md`.

### Domain docs

Before domain exploration, follow the single-context layout
and consumer rules in `docs/agents/domain.md`.
