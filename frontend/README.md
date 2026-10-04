# InvSys desktop frontend

This is the live dashboard/catalog, Receive, standard and nested BOM Ship, and
History slice for issues #7–#10, based on approved layout A.
The reference remains on `prototype/invsys-phase0`; fixture workflows are not
included here. Python InventoryStore owns stock, low-stock status, and persistence.

```bash
npm ci
npm run check
npm run build
```

`npm run build` checks types and then builds the assets. CI runs `npm run check`
and `npm run build:assets` as separate steps so failures are easy to identify
without checking types twice.

Node must satisfy the locked Vite release's engine requirement (Node 20.19+ or
22.12+). Development uses `npm run dev`, but a normal browser has no Python
bridge: it deliberately shows an unavailable-connection state. Use the desktop
launcher from the repository root to exercise live operations. No frontend test
runner has been introduced.

Vite builds a classic IIFE script and CSS; `scripts/build-html.mjs` writes the
relative local HTML entry point. `dist/` contains `index.html`, `app.js`, and
`style.css`. This avoids ES-module file-origin restrictions without adding a
server or build plugin. All icons and styles are bundled locally.

`src/bridge.ts` defines the strict use-case client and response DTOs. The shell
waits for `pywebviewready`, handles an already-ready bridge, and reports a timeout
with an explicit reconnect action. Requests never fall back to fixture data.
Read failures offer Refresh/Retry; mutations are not automatically retried. An
uncertain create preserves entries and requires closing and refreshing the
catalog to reconcile against an authoritative part read before resubmission.

Receive and Ship forms retain drafts during session navigation and refresh current
availability on return. Receive keeps part/location after confirmed success and
clears quantity/lot/reference/notes, including operator-verified completion after
an uncertain response. Validation failure and unresolved uncertainty preserve
the draft notes. Standard Ship reads a fresh selected-lot review before
confirmation, then requires Ship another after success. Existing nested BOM
parents use Python-generated aggregated leaf requirements and lot allocations,
including multiple lots for one material. Confirmation requires a matching
session-local review token. A shortage or changed allocation leaves inventory and
audit records unchanged; changed allocations preserve the draft, show a refreshed
plan, and require another explicit review and confirmation. Parent and intermediate
assembly stock stays unchanged. BOM editing and exploration remain in the original
PySide6 application.

History searches real transactions by part, lot, operator, or shipment reference,
with visible search/type filters and pagination. Its read-only drawer uses
persisted transaction IDs and shipment links, and displays durable per-lot
component consumption snapshots. Dashboard activity and shipment success open
the corresponding audit details. History refreshes on entry, revisit, and after
mutations while preserving filters, selection, and table position.

An uncertain stock submission locks its preserved draft. Read current stock and
audit records for the submitted part, compare the saved request with the records,
and explicitly verify completion or absence before starting another entry or
unlocking the draft. Reads do not retry the mutation or infer completion from a
balance alone. This is operator-assisted reconciliation, without durable request
deduplication or a cross-process concurrency guarantee.

Search/filter/sort state stays local. Opening a native dialog does not rebuild
the catalog. Dialogs trap focus, support Escape, restore focus, and the drawer
restores table/page position. Both themes use visible keyboard focus and reduced
motion styles. Operator and explicit theme choice use existing Python settings.

See [desktop launch and validation](../docs/frontend/desktop.md).
See [complete prototype acceptance and remaining gaps](../docs/frontend/prototype-acceptance.md).
Part details have a contextual View History action; a failed transaction or
shipment detail read offers Retry details inside the open drawer.
