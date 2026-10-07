# Live desktop inventory workflows

The pywebview frontend covers the dashboard, Parts catalog, Receive, standard and
nested BOM Ship, and History, using [approved layout A](phase0-design.md). The
original PySide6 application remains available for every other workflow. See the
[frontend roadmap](roadmap.md) for remaining phases.

## Launch

Install Python dependencies in your environment and build the frontend:

```bash
pip install -r requirements-desktop.txt
npm ci --prefix frontend
npm run build --prefix frontend
python inventory_desktop.py
```

The Qt backend needs PySide6 with Qt WebEngine, QtPy, a graphical desktop, and the
platform's Qt runtime libraries. Linux requires a working X11/Wayland display;
this launcher is not an offscreen browser. Tested here with Python 3.14, pywebview
6.2.1, QtPy 2.4.3, and the installed PySide6 WebEngine. Frontend dependencies follow
the npm lockfile (Vite, strict TypeScript, lucide; no framework).

Normal source launch uses the existing `data/inventory.db`, `backups/`, and
`logs/` paths. Startup backs up an existing database before opening InventoryStore,
with the existing retention policy. The original `python inventory_visualizer.py`
launcher remains available for all inventory operations.

Review with an explicit disposable database:

```bash
python inventory_desktop.py --database /tmp/invsys-review/inventory.db
python inventory_desktop.py --database /tmp/invsys-smoke/inventory.db --smoke-check
```

An explicit database keeps backups and `logs/desktop.log` beside that database.
Importing the bridge does not initialize the original application's shared store.
The smoke command saves operator `Desktop smoke`, creates `DESKTOP-SMOKE` if
absent, inspects its drawer, receives lots, ships standard stock, and exercises
drafts, repeat entry, shortages, duplicate clicks, and lost-response reconciliation.
It also prepares a fresh disposable nested/shared
BOM, reviews a multi-lot allocation, rejects shortage and stale allocation,
reconfirms, and inspects History and component snapshots.
It verifies the complete stock/audit result through a reopened store. Use a disposable file: these are real writes. Repeat the command to check
startup backups and restart reads. No seed inventory is inserted by the launcher.

The retained smoke also exercises contextual part-to-History navigation, failed
History detail retry, explicit refresh after another operator's receipt, and
uncertain BOM reconciliation, including a failed recovery read. It uses real Qt
keyboard events for all four dialogs and captures five pages and dialogs in both
themes at four sizes to `smoke-captures/` beside the database. On Linux, use
`QT_API=pyside6 QTWEBENGINE_CHROMIUM_FLAGS=--force-prefers-reduced-motion`
to select PySide6 and exercise reduced-motion behavior.

Built assets load directly over `file://` with `http_server=False`. An explicit
file URI avoids pywebview automatically starting a server for a bare local path
([pywebview usage](https://pywebview.flowrl.com/guide/usage.html)). The build uses
relative local assets ([Vite build documentation](https://vite.dev/guide/build.html)).
There is no Vite process, HTTP server, CDN, or network inventory service required.

## Basic package proof

Full installers and release packaging remain deferred. A Linux one-directory
PyInstaller proof includes the built frontend:

```bash
pip install pyinstaller
pyinstaller --noconfirm --name invsys-desktop --onedir \
  --add-data frontend/dist:frontend/dist \
  --hidden-import webview.platforms.qt \
  --hidden-import PySide6.QtWebEngineWidgets \
  --hidden-import PySide6.QtWebEngineCore \
  --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 \
  --exclude-module tkinter --exclude-module gi inventory_desktop.py
./dist/invsys-desktop/invsys-desktop --database /tmp/invsys-packaged/inventory.db --smoke-check
```

Packaged launch requires `--database` explicitly, so it cannot silently open an
inventory file inside a bundle or temporary extraction directory. Select the
existing operational file explicitly when appropriate. `--assets` overrides the
built asset directory for local review; it is not needed for bundled assets.
This package is a platform-specific smoke artifact, not a distributable release.

## Scope and contract

Available: live dashboard counts/low-stock/activity, header operator save,
remembered light/dark choice, catalog search/filter/sort, part creation, and
read-only drawer with fields and lot/location balances. Low-stock entries open
live parts; the attention panel shows five entries and links to all low-stock
parts. Active and low-stock indicators are separate. Receive and standard Ship
open from navigation, dashboard actions, and part details, adopting the selected
part's default location. Confirmed receipt success retains part/location and clears
quantity/lot/reference/notes, including operator-verified completion after an
uncertain response. Validation failure, unresolved uncertainty, and navigation
preserve draft Notes. Shipment confirmation shows selected-lot stock separately
from location stock, quantity, recipient, operator, optional details, and the
actual lot remaining. Success shows the generated shipment number and requires
Ship another. Both use persistent results and a temporary toast. The frontend never computes
stock or invents catalog fields.

Deferred workflows are identified in the shell and drawer (see
[below](#deferred-workflows)). Dashboard activity opens the exact immutable
History record using its existing database transaction ID.

The bridge exposes dashboard, preferences, save operator/theme, locations,
part search/detail/create, stock context, receive, standard shipment preview,
standard ship, BOM preview/confirmation, searchable paged History, and
transaction/shipment inspection. Stock context contains current part/lot/location balances,
BOM presence, and that part's immutable transactions and shipments for recovery. It validates input shapes/types before using the store
and returns `{ok: true, data}` or `{ok: false, error: {code, message}}`. Stable
codes: `VALIDATION`, `DUPLICATE`, `NOT_FOUND`, `INTERNAL`, and `PLAN_CHANGED` for a rejected BOM allocation. Unexpected exceptions
are logged and return a safe message. Private helpers, store/session access,
SQL, arbitrary settings, and generic balance writes are not exposed. Requests from this
window are serialized.

InventoryStore owns the catalog, dashboard, Part detail, stock-context, and
shipment-review read modules. Each read uses an explicit SQLite read transaction
so its quantities, status, and included audit records describe one committed
database state, even when another application writes during the read. The next request
sees subsequent commits. The bridge validates requests and translates errors;
it does not assemble these results from separate store reads.

Desktop standard and BOM reviews use `review_standard_shipment` and
`review_bom_shipment`. Each returns eligibility, quantities, and complete stock
context from one snapshot. BOM allocation and build capacity share the same
availability calculation. The bridge parses request fields, translates errors,
and retains the session-local reviewed plan; it performs no separate inventory
checks before the review. Existing eligibility remains: standard review requires
an active Location, while BOM review accepts any existing Location. An existing
Lot with no balance at the selected Location is a shortage, not a missing Lot.

Catalog quantities are aggregated together. Part detail and stock context query
the selected Part's balances and audit records directly. Stock context retains
that Part's complete transaction and shipment lists, newest first, because
uncertain-submission recovery depends on their lengths. Response size still
grows with that Part's own history. Catalog search retains Python's Unicode
case folding and the existing sort order.

The read snapshot does not reserve stock or authorize a later shipment; mutations
still validate at submission. The original PySide6 screens retain their existing
read paths. No schema or inventory rules changed.

## Drafts and uncertain submissions

Drafts stay in the mounted forms for this session. Returning refreshes current
availability and invalidates any prior shipment review. Input is locked while a
mutation is pending; no mutation is automatically retried. If its response is
lost or Python reports an unexpected failure, preserve the submitted request and
lock further submissions. Read current stock and the audit records added since
the pre-submit read. Compare quantity, lot, location, operator, reference, receipt
notes, and shipment details before explicitly verifying completion or unlocking
an operation that did not complete. A failed recovery read keeps the draft locked.

Reconciliation is operator-assisted: other operators/processes can produce similar
records, and a stock total cannot prove completion. There is no durable request
identifier or automatic deduplication. Consistent stock-context reads do not add
a cross-process guarantee for mutation deduplication or completion detection.
Use History to inspect shipment transactions and per-lot component snapshots. Do not unlock
and repeat an entry whose completion is still uncertain.

Existing BOM parents use Python's aggregated leaf requirements and deterministic
positive-stock lot allocation. The form hides parent-lot selection and shows part
low-stock status, build capacity, and shipment readiness separately. Shortage
previews remain readable but cannot be confirmed. Only leaf stock is consumed.

BOM preview returns a session-local, opaque review ID tied to the exact normalized
shipment draft and server-held InventoryStore plan. Confirmation requires that
review, then the existing store compares allocations within its atomic shipment
transaction. Reviews are single-use and bounded to the latest 128 ready previews;
a missing/expired/mismatched review requires another explicit review. Reviews do
not survive process restart. Changed allocation rejects the submission without
writes; the form preserves input, reads and displays updated allocations, and
requires Review shipment and confirmation again. It never retries a mutation.

History filters and pages in Python, returning at most 50 records per page. Search
part, lot, operator, custom reference, or generated shipment number; type/search
filters stay visible. Table selection and position survive drawer inspection.
The drawer shows transaction details, linked standard/BOM shipment data and
persisted consumption snapshots. Links follow the existing shipment foreign key,
even when a standard shipment has a custom reference. No identifiers or component
quantities are reconstructed in JavaScript. Success includes Inspect shipment;
mutations and returning to History refresh reads while preserving filters.

## Deferred workflows

The shell directs operators to the original application for Move, Adjust, part
editing/deactivation, location administration, BOM editing and exploration, CSV
import/export, manual backup/restore, and operational Settings. Global search is
part search only.

Not yet validated: Windows/macOS packages and installers, screen-reader review,
human operator acceptance, and performance/release hardening. The native smoke is
scripted desktop acceptance, not exhaustive accessibility review. Mutation
reconciliation is operator-assisted, without durable request deduplication.
