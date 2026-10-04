# Live desktop inventory workflows

Issues [#7](https://github.com/theozex4ever/InvSys/issues/7),
[#8](https://github.com/theozex4ever/InvSys/issues/8), and
[#9](https://github.com/theozex4ever/InvSys/issues/9) implement dashboard/catalog,
receiving/standard shipping, and nested BOM shipping/History slices of
[#6](https://github.com/theozex4ever/InvSys/issues/6), using
[approved layout A](phase0-design.md). The full frontend migration remains in progress.

Issue [#10](https://github.com/theozex4ever/InvSys/issues/10) validates this complete
working slice. See [current acceptance results, repeatable native checks, and
remaining migration gaps](prototype-acceptance.md).

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
the prototype's npm lockfile (Vite, strict TypeScript, lucide; no framework).

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
part's default location. Receipt success retains part/location/notes and clears
quantity/lot/reference. Shipment confirmation shows selected-lot stock separately
from location stock, quantity, recipient, operator, optional details, and the
actual lot remaining. Success shows the generated shipment number and requires
Ship another. Both use persistent results and a temporary toast. The frontend never computes
stock or invents catalog fields.

Move/Adjust, BOM editing/exploration, part editing and
activation, location administration, and operational Settings are deferred and
identified in the shell/drawer. Dashboard activity opens the exact immutable
History record using its existing database transaction ID.
Continue those workflows in the original application.

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

## Issue #7 validation record (2026-10-01)

Automated integration checks use the agreed public bridge boundary against real
temporary SQLite files. They cover dashboard/empty reads, setting persistence,
search/filter/sort, per-lot/location balances, creation/restart, invalid requests,
unknown records, separate active/low-stock state, and safe logged exceptions.

Native smoke checks exercise real pywebview/Qt WebEngine, built local assets,
operator save, part creation, live drawer, theme save, and restart persistence.
A broader native keyboard/viewport check uses disposable real catalog/lot data:
light/dark at 1366 × 768, 1920 × 1080, and 800 × 650; no horizontal page overflow;
Tab/Shift+Tab inside both dialogs; Escape and focus restoration; low-stock detail
navigation; duplicate feedback retaining input; search and page position retained
when a drawer closes. These checks exposed and led to explicit dialog focus
trapping and scroll restoration.

Exact final gate and package results are recorded below when run. Reduced-motion
CSS is implemented; OS-level reduced-motion emulation, Windows/macOS packaging,
and human operator usability acceptance remain follow-up checks. Do not treat the
native probe as exhaustive accessibility or release validation.

Final executed results:

- `QT_QPA_PLATFORM=offscreen pytest`: **215 passed** (6.40 s).
- `npm run check --prefix frontend`: strict TypeScript passed.
- `npm run build --prefix frontend`: passed; HTML, IIFE JS and CSS emitted.
- Ruff lint and format checks on new Python modules/tests: passed.
- Native source launcher `--smoke-check`: passed against a disposable database.
- Linux PyInstaller one-directory build: passed. Refreshed the bundle's frontend
  files after the final UI fixes; packaged `--smoke-check` passed with local assets,
  no HTTP server, operator/create/drawer behavior, and reopened-database reads.
- Broader native Qt keyboard/viewport smoke: passed after the focus and scroll
  fixes described above. Viewport captures were visually inspected.
- Native recovery smoke: passed. A real create committed before an injected lost
  transport response; repeated submit was suppressed, entries stayed intact,
  reconciliation used the submitted number despite later edits, and a delayed
  reconciliation could not replace results for a newer search.
- Native readiness smoke without a use-case bridge: passed; readable unavailable
  state, disabled mutations, and reconnect action. Packaged restart also produced
  a startup backup containing the saved operator.
- Two-axis code review: Standards **0 remaining findings**, Spec **0 remaining
  findings** after fixing uncertain-create identity and stale read handling.

## Issue #8 validation record (2026-10-01)

Executed against disposable SQLite databases and built local frontend assets:

- Full offscreen regression gate: **282 passed** (9.83 s), including the original
  store and PySide6 UI tests and 67 new public bridge stock scenarios.
- Focused bridge gate after review: **74 passed** (3.94 s).
- Strict TypeScript check and Vite production build: passed.
- Ruff lint and format checks for changed Python modules/tests: passed.
- Extended native `--smoke-check`: passed receipt repeat entry/reset, preserved
  notes, receipt/ship drafts, selected-lot shortage, real shipment confirmation,
  success/Ship another, duplicate clicks, lost responses after committed receipt
  and shipment, failure before sending a receipt, explicit audit reconciliation,
  and complete stock/transaction/shipment equality after reopening the database.
- Native delayed-preview probe reproduced a late confirmation after navigation.
  The fixed workflow rejects it, including leaving and returning while the preview
  is pending; the retained smoke command includes this regression check.
- Native recovery checks verify persistent received quantity/current stock and
  reviewed shipment numbers after recovery details are closed.
- Native operator-edit regression: a delayed availability read still enables
  shipment review, while a delayed preview is cancelled and requires fresh review.
- Native UI probe: dashboard and part-context actions, a non-Stock default location,
  refreshed drafts, BOM submission blocking, real Qt Tab/Shift+Tab focus trapping,
  Escape and focus restoration passed. Both themes at 1366 × 768, 1920 × 1080,
  800 × 650, and 640 × 480 had no horizontal page overflow. Receive captures were
  visually inspected; small windows use vertical scrolling to reach the actions.
- Two-axis review: Standards **0 remaining findings**; Spec **0 remaining findings**
  after the preview freshness and persistent recovery-feedback fixes.

The native UI probe used the real pywebview/Qt WebEngine shell, rather than a
new browser test framework. Broader human operator acceptance, Windows/macOS
packaging, and exhaustive accessibility checks remain follow-up work. Issue #8
adds standard stock workflows; BOM shipment integration and History remain deferred.


## Issue #9 validation record (2026-10-02)

Executed using real disposable SQLite stores and production local assets:

- Full offscreen pytest gate: **317 passed** (14.26 s), retaining the original
  service, bridge, database, and PySide6 regressions; 35 new bridge scenarios.
- Focused History/BOM integration gate: **35 passed** (4.06 s). Covers custom
  shipment references/FK linkage, bounded paging and literal search, detached
  immutable results, unknown records, safe logged database failures, nested/shared
  leaves, multi-lot consumption, review identity/draft validation, shortage and
  stale rollback/reconfirmation, unchanged assemblies, restart persistence, and
  snapshots surviving later BOM edits, and custom BOM reference search.
- Strict TypeScript and Vite production build: passed. Ruff lint and format checks
  on changed Python bridge/smoke/test files: passed. Existing store formatting was
  preserved outside the new read methods.
- Extended native source `--smoke-check`: passed standard stock regressions plus
  BOM shortage, shared-leaf multi-lot review, changed allocation rejection and
  explicit reconfirmation, duplicate-click suppression, immediate shipment/durable
  snapshot inspection, History search/type/drawer, dashboard record links, and
  reopened-database equality with unchanged parent/intermediate stock.
- Native Qt keyboard/viewport probe: passed History pagination and selected-row
  scroll restoration, real Tab/Shift+Tab focus trapping, Escape and focus restore
  in BOM confirmation and History drawers. Both themes at 1366 × 768,
  1920 × 1080, 800 × 650, and 640 × 480 had no horizontal page/dialog overflow.
  Representative BOM and History captures were visually inspected. Dialogs scroll
  vertically to reach complete allocations and confirmation actions.

On this workstation the native command used `QT_API=pyside6` to select the
installed PySide6 backend instead of an incomplete PyQt5 installation. The probe
used the existing pywebview/Qt shell; no new browser test framework was added.
Two-axis code review: Standards **0 remaining findings**, Spec **0 remaining
findings**, after adding persisted custom BOM references to History search.

Windows/macOS packaging, exhaustive accessibility testing, and human operator
acceptance remain follow-up work. This ticket does not complete the migration.
