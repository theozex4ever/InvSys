# Live desktop inventory workflows

The pywebview frontend covers the dashboard, Parts catalog, Receive, standard and
nested BOM Ship, Move, Adjust Count, BOM authoring, a read-only BOM explorer, History, and Settings CSV exports/backups/Parts, Inventory receipt and BOM imports, using
[approved layout A](phase0-design.md). The
original PySide6 application remains available for every other workflow. See the
[frontend roadmap](roadmap.md) for remaining phases.

Use the [migration acceptance baseline](acceptance.md) for disposable workflow
and large-workload inventories, capability classifications and retirement gates.

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

An explicit database keeps backups, exports and `logs/desktop.log` beside that database.
Importing the bridge does not initialize the original application's shared store.
The smoke command saves operator `Desktop smoke`, creates `DESKTOP-SMOKE` if
absent, inspects its drawer, receives lots, ships standard stock, and exercises
drafts, repeat entry, shortages, duplicate clicks, and lost-response reconciliation.
It also creates the disposable `DESKTOP-EDIT` Part and exercises edit, unsaved-edit
confirmation, validation, duplicate clicks, lost-response recovery (including a
failed recovery read), stocked deactivation and reactivation.
It also prepares a fresh disposable nested/shared
BOM, reviews a multi-lot allocation, rejects shortage and stale allocation,
reconfirms, and inspects History and component snapshots. It then authors
nested/shared definitions on the BOM page and exercises update, rejection,
removal confirmation, duplicate clicks, a lost response with failed and then
successful read-back, review invalidation after edits, and unchanged shipment
snapshots, and verifies the result after reopening the store.
It creates a manual backup in Settings, checks the latest-backup status and the folder
requests (recorded, not opened, so the smoke never spawns a file manager), and shows a
failed folder request as an error. It reopens the backup read-only. It verifies the complete stock/audit result through a reopened store. Use a disposable file: these are real writes. Repeat the command to check
startup backups and restart reads. No seed inventory is inserted by the launcher.

The export smoke uses Settings to write all five CSV kinds, checks actual headers,
row counts, Lot and audit metadata and persisted BOM shipment summaries, and confirms
that every file stays in the selected inventory's export folder. It checks duplicate
clicks, navigation during an export, a real blocked export directory, uncertain-response
feedback and unchanged inventory. Native Enter, Tab and Shift+Tab exercise exports in
both themes at the minimum window size; folder opening is recorded by the smoke host.

The retained smoke also exercises Move on its own disposable `DESKTOP-MOVE` Part:
drafts across navigation, same-Location rejection, duplicate clicks, Python
before/after quantities, a lost response with a failed recovery read, stale-stock
rejection and contextual entry, checking persisted balances and paired records.
It also exercises contextual part-to-History navigation, failed
History detail retry, explicit refresh after another operator's receipt, and
uncertain BOM reconciliation, including a failed recovery read. It uses real Qt
keyboard events for all four dialogs and captures all ten pages and dialogs in both
themes at four sizes to `smoke-captures/` beside the database. On Linux, use
`QT_API=pyside6 QTWEBENGINE_CHROMIUM_FLAGS=--force-prefers-reduced-motion`
to select PySide6 and exercise reduced-motion behavior. The smoke also explores the
disposable nested BOM, compares the graph with `explore_bom`, fits/zooms/selects,
fails and refreshes a read, and checks that exploring adds no transactions.

The smoke also creates Parts through a double click and a lost response, once after
the request committed (`DESKTOP-CREATE-*`) and once before it was sent
(`DESKTOP-UNSENT-*`). Each time the form stays locked through a failed read-back;
a successful read offers one explicit created/not-created decision, and Python
rejects a duplicate resubmission. Manual backup is double-clicked, then loses its
response after and before writing. Create backup stays disabled through a failed
read and a read that cannot list the backups (`backup_error`), and until the
operator confirms the re-read backups; nothing is retried. Last, real Qt Ctrl+1–9 and Ctrl+K (which selects existing search text) keys reach every numbered
destination and its primary input with visible focus, are ignored behind an open
dialog, and leave catalog filters/sort/selection, the contextual Move draft and
History search/sort intact. History rows must match Python's order for text
searches and column sorts. A rendered audit, first proven against a planted
failure, checks WCAG text contrast and accessible names/labels on all ten pages and
the Part drawer in both themes, including SVG text over the BOM graph's node cards.

Built assets load directly over `file://` with `http_server=False`. An explicit
file URI avoids pywebview automatically starting a server for a bare local path
([pywebview usage](https://pywebview.flowrl.com/guide/usage.html)). The build uses
relative local assets ([Vite build documentation](https://vite.dev/guide/build.html)).
There is no Vite process, HTTP server, CDN, or network inventory service required.
The complete frontend uses about 33.6 KB gzipped JavaScript (33,609 bytes). Ticket
#51 raised the JavaScript budget from 33 KB to 34 KB as an explicit decision for
numbered destinations, History search/sort and a distinct Adjust icon, after
shared helpers replaced per-module copies (CSS 8 KB, HTML 1 KB unchanged). Review
added explicit Part creation and backup recovery decisions; about 0.4 KB of
headroom remains; further increases need another explicit decision.

## Standalone bundle

Repeatable offline Linux and Windows bundles (PyInstaller one-directory, exact built
assets, Qt WebEngine) are built and smoke-tested with `scripts/package_bundle.py`; see
[standalone offline bundle](packaging.md) for build, install, prerequisites, data
selection, readable failures, the twice-run package smoke, CI and recorded
evidence. Packaged launch requires `--database` explicitly, so it cannot silently
open an inventory file inside a bundle or temporary extraction directory. `--assets`
overrides the built asset directory for local review; it is not needed for bundled
assets. A macOS bundle, installers, signing and release publication remain
outstanding.

## Scope and contract

Available: live dashboard counts/low-stock/activity, header operator save,
remembered light/dark choice, catalog search/filter/sort, part creation, and
drawer with fields, lot/location balances, and Part editing: description, minimum
quantity and default Location (the number is immutable), plus deactivate and
reactivate without deletion. Deactivating a Part with stock names the units on
hand and needs confirmation, which the bridge enforces. Cancelling or closing over
unsaved edits asks first. A lost response locks the preserved edit until the
operator reads the current Part and explicitly decides; mutations are never
retried automatically. Low-stock entries open
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

Keyboard destinations keep the original application's numbering: Ctrl+1 Dashboard,
2 Parts, 3 BOM, 4 Receive, 5 Ship, 6 Move, 7 History, 8 Settings and 9 Adjust (Cmd on
macOS). Ctrl+K opens Parts search. Shortcuts work from any field, are ignored while
a dialog is open, and keep drafts, filters and selections like the sidebar. After
the page loads they focus its primary input: the first Needs-attention Part, catalog
search, BOM parent, the Part of Receive/Ship/Move/Adjust, History search, or the page
heading for Settings and for a locked form. The sidebar shows each shortcut and exposes it through `aria-keyshortcuts`;
the BOM explorer, which the original lacked, has no number. Sidebar clicks keep
focus on the navigation button, so keyboard users can continue through it.

The bridge exposes dashboard, preferences, save operator/theme, locations,
part search/detail/create/edit/active state, BOM definition read/save/remove, stock context, receive, standard shipment preview,
standard ship, BOM preview/confirmation, Move preview/confirmation, Adjust Count
preview/submission, read-only BOM exploration, searchable paged History, transaction/shipment inspection,
and Settings CSV export/backup/folder utilities and reviewed Parts/Inventory receipt/BOM CSV imports. Stock context contains current part/lot/location balances,
BOM presence, and that part's immutable transactions and shipments for recovery. It validates input shapes/types before using the store
and returns `{ok: true, data}` or `{ok: false, error: {code, message}}`. Stable
codes: `VALIDATION`, `DUPLICATE`, `NOT_FOUND`, `INTERNAL`, `PLAN_CHANGED` for a rejected BOM allocation,
`STALE` for changed expected stock, `CONFIRMATION_REQUIRED` for unconfirmed
stocked deactivation or large count corrections, and `FILE_ERROR`/`UNAVAILABLE`
for utility failures. Unexpected exceptions
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

## BOM explorer

The BOM explorer page shows a nested BOM for a chosen assembly, Location and build
quantity. `explore_bom` returns, from one read snapshot, the nested tree (each node
with required quantity, quantity per parent, stock at the Location, Build capacity
and capacity level), the Leaf requirements aggregated across all paths with their
shortages, overall Build capacity, and the count of short materials. The tree is a
phantom view: assembly stock is shown but never consumed. Capacity is Critical at
100 or fewer final builds, Low through 500, otherwise Ready; this planning warning
is independent of shortages for the requested quantity. Shortages describe stock only;
shipping eligibility (for example an inactive assembly) is decided at shipment review. A part without a BOM is
returned as a single node. Inactive root parts can be explored; inactive
components, circular definitions and BOMs expanding past 5,000 nodes return a
`VALIDATION` error instead of a graph. Exploring never writes inventory.

The graph is hand-built SVG (no graph library). Drag or the arrow keys pan the
focused graph, Ctrl + wheel or +/− zoom, 0 or Fit fits, and arrow keys on a node move
between parent, child and siblings. Status is shown as text and a glyph with a
distinct border style, not by colour alone. A failed or stale read replaces the
graph with the error; Refresh rereads authoritative data. Advanced focus/collapse,
breadcrumbs and command search remain deferred.

## Move

Move transfers a positive-stock Lot between Locations (`frontend/src/move.ts`).
The form takes Part, source (From), destination (To), Lot, quantity, optional
reference and the header operator. Opening it from a Part adopts that Part's
default Location as the source; otherwise source starts at Stock and destination
at Shipping Bench when those Locations exist. The Lot list offers only Lots with
stock at the source. `preview_move` reads source and destination Lot and Location
totals before and after from one snapshot (`review_move`) and writes nothing; the
confirmation dialog shows those authoritative numbers for both Locations. `move`
calls `InventoryStore.move`, which posts `MOVE_OUT` and `MOVE_IN` in one database
transaction, then returns the refreshed stock context. Same-Location, unknown
Lot/Location, inactive Part, and insufficient stock reject with readable messages
and no writes; a review never reserves stock, so a stale confirmation is
rejected at submission and availability is re-read.

Drafts survive navigation and availability refreshes on return. Duplicate
submissions are blocked while a request is pending. An ambiguous transport or
internal failure locks the draft until the operator reads current stock and audit
records and states whether the move completed; a failed recovery read keeps the
lock. After confirmed success the dashboard, Parts, and History reload.

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

History filters, sorts and pages in Python, returning at most 50 records per page.
Case-insensitive text search (Unicode case folding, like the catalog) covers the original columns (timestamp, transaction
type, Part, Lot, source and destination Location, operator, reference) and Notes,
plus generated shipment numbers and shipment references; it combines with the exact
type filter. Sort by Time, Type, Part, Lot, Qty (signed, numeric), From, To, Operator
or Reference, ascending or descending; ties follow record ID in the same direction,
so pages never overlap.
The default is newest first. Clear filters and contextual Part History restore it.
Search, type and sort stay visible. Table selection and position survive drawer inspection.
The drawer shows transaction details, linked standard/BOM shipment data and
persisted consumption snapshots. Links follow the existing shipment foreign key,
even when a standard shipment has a custom reference. No identifiers or component
quantities are reconstructed in JavaScript. Success includes Inspect shipment;
mutations and returning to History refresh reads while preserving filters.

## BOM authoring

The BOM page (`frontend/src/bom.ts`) maintains the direct components of nested
definitions. `bom_definition` returns one Part's direct components and direct
parents from one snapshot; `save_bom_component` adds a component or, when the
link exists, updates its quantity; `remove_bom_component` requires
`confirmed: true`. Self-reference, cycles, unknown Parts and quantities outside
1–2147483647 are rejected by the store and bridge with no change. Each success
returns the refreshed definition. Edits never write stock or audit records, and
persisted shipment component snapshots are unaffected. A reviewed BOM shipment
whose allocation no longer matches after an edit is rejected as `PLAN_CHANGED`
and needs a fresh review.

The page blocks duplicate submissions and preserves its draft on rejection. After
a transport or internal failure it locks editing until the operator reads the
authoritative definition and explicitly states whether the change applied; a
failed read keeps the lock and nothing is retried automatically.

## Adjust Count

The Adjust page reconciles a counted total for an existing Lot at a Location,
including zero-stock Lots. `preview_count` returns Python's expected quantity,
difference and whether the large-correction threshold (absolute difference of at
least the larger of ten units or half the expected quantity, rounded down) requires
confirmation. `adjust_count` re-reads the Lot, rejects a changed expected quantity
(`STALE`) or an unconfirmed large correction (`CONFIRMATION_REQUIRED`), then posts
the `COUNT_CORRECTION` transaction with the reason as its reference. A Lot with no
balance row at the Location cannot be counted there. Inputs are preserved on
rejection; success clears count and reason and keeps a persistent result. A lost
response locks the draft until the operator reads current stock and audit records
and explicitly verifies completion or absence; a failed recovery read keeps the lock.

## Settings: CSV exports, backups and folders

Settings is the shared destination for operational utilities. It shows the database
and the backup, export and log folders chosen at launch: source launch uses `data/`,
`backups/`, `exports/` and `logs/` under the checkout or `INVSYS_HOME`; an explicit
`--database` keeps all three folders beside that file. Packaged launch still requires
`--database`.

- **Create backup** writes `inventory-YYYYMMDD-HHMMSS-manual.db` with SQLite's backup
  API, reopens and integrity-checks the copy, and only then applies the same retention
  of 20 newest files (startup backups are kept); a failed check removes the new copy
  and leaves every earlier backup in place. The
  page then shows the latest backup's name, time and size and the number on disk.
  A missing database file or an unwritable/unreadable backup folder is reported as
  an error; nothing is reported as created unless the file exists.
- **Open backups/exports folder** asks the platform file manager (`xdg-open`, `open`
  or `os.startfile`) to show the folder for the selected inventory, creating it when
  absent. Only those two named folders can be requested. If the opener is missing or
  fails, the error is shown instead of a success message.
- **Export Parts / Inventory / Transactions / Shipments / BOM definitions** writes
  one UTF-8 CSV using the existing export service. Files use the existing
  `<kind>_YYYYMMDD_HHMMSS.csv` naming (the same kind within one second replaces that
  filename) and fields, including per-Lot balances, transaction metadata and
  persisted shipment component summaries. Exporting does not change inventory.
  Settings shows the row count, full file path and destination; **Open exports
  folder** opens that destination. All utility buttons are disabled during the
  request, including when navigating away and back. File failures display an error;
  after an uncertain response, inspect the exports folder before retrying. An
  interrupted write can leave an incomplete file; it is never reported as a success.

Python wiring: `UtilityContext` (`inventory_control/utilities.py`) is the launch-aware
set of paths; `DesktopHost` is the narrow native interface (`open_folder`,
`choose_file`) with `NativeHost` as the pywebview implementation. `InventoryBridge`
accepts both and exposes `utility_context`, `create_backup`, `export_csv` and `open_folder`.
`choose_file` returns the chosen path or `None` on cancel and is the seam for the
CSV import slice; it is not exposed to the page on its own. The bridge keeps
`_utilities` and `_host` private because pywebview publishes every public attribute.
The frontend side is `frontend/src/settings.ts`; later utilities add sections there.

## Parts CSV import

In Settings, select **Select Parts CSV**. The native dialog starts beside the
launch-selected database; cancellation keeps the previous review. The preview
shows the selected path, total/valid data rows, commit eligibility and every
row/field error or warning. Required fields are `part_number` and `description`;
optional fields remain `default_location`, `minimum_quantity` and `active`.
Existing numbers update their catalog fields; new numbers create Parts. Ignored
legacy fields such as `barcode` produce warnings. Stock and History stay intact.

Every CSV import kind rejects ambiguous structure instead of guessing:
duplicate column names (after trimming and case folding), values beyond the named
columns (for example an unquoted comma inside `1,000`) and malformed quoting are
errors, in both applications.

Confirm the reviewed catalog changes using the checkbox, then **Commit Parts
import**. Python rereads the selected file, rejects changed bytes, validates again,
and verifies a pre-import backup in this inventory's backup folder before writes.
Backup failure blocks the import. Parts rows retain the existing single-transaction
behavior: a database failure rolls back all rows. This does not change the failure
semantics of other import kinds. Success displays the imported row count and backup
path and refreshes catalog, dashboard and cached Part details.

Selection, issues and results survive navigation. A lost response locks selection
and submission: **Check import outcome** reads the session-local attempt status
and then current Parts, dashboard and History; any failed read keeps the lock. Accept a reported completion explicitly, or inspect
the catalog and backups and explicitly allow a new review. No mutation is retried
automatically. Reviews and recovery status last for this application session;
after restart, inspect the catalog and backup before selecting input again.

The typed API adds `select_import(kind)`, `commit_import` (review ID,
confirmation, operator) and `import_status`. Paths remain owned by the native
selection and Python service. The review lifecycle in `frontend/src/imports.ts`
renders one Settings panel per enabled kind (`parts`, `inventory`, `bom`); each kind
keeps its own current review, so selecting one kind never supersedes another.
Public bridge tests use real temporary SQLite. The native
smoke drives real Qt file selection/cancellation, invalid rows and warnings,
changed-file rejection, confirmation, duplicate clicks and lost-response recovery,
then verifies imported catalog fields after reopening the database.

## Inventory receipt CSV import

In Settings, select **Select Inventory CSV**. Selection, cancellation, the preview
and lost-response recovery follow the Parts lifecycle above. Required fields are
`part_number`, `location`, `lot_number` and `quantity`; optional `reference`
(default `CSV import`) and `notes` are kept on each receipt. Rows are blocking
errors when the Part is missing or inactive, the Location is missing, the Lot is
blank, the quantity is not a whole number from 1 to 2147483647, or a
Part/Location/Lot repeats in the file. Other columns, such as `description` or
`operator` from an Inventory export, produce warnings and are not imported.
The quantity limit matches desktop Receive. It also applies to the original
application's Settings import, which previously accepted larger values: an
intentional compatibility restriction.

Confirm the receipts using the checkbox, then **Commit Inventory import**; an
operator name is required and attributes every receipt. Python rereads the file,
rejects changed bytes, and validates again against current inventory: if, for
example, a Part was deactivated after review, the commit is rejected as stale and
needs a new selection. It then verifies a pre-import backup before writes. Each row
posts one `RECEIVE` through the Stock ledger; the existing service writes all rows
in one database transaction, so a failure leaves stock and History unchanged.
Committing the same file again in a new review receives the stock again; inspect
History before re-importing. Success refreshes Parts, dashboard, cached Part
details, History and the latest-backup status.

The native smoke drives real dialog selection/cancellation, a blank-Lot error,
blocked commit without an operator, changed-file rejection, duplicate clicks and
lost-response recovery with failed reads, checks refreshed History and dashboard,
and verifies the Stock balances after reopening the database.

## BOM CSV import

In Settings, select **Select BOM CSV**. Selection, cancellation, the preview and
lost-response recovery follow the Parts lifecycle above. Required fields are
`parent_part_number`, `component_part_number` and `quantity_per`; the BOM export
has exactly these columns. Rows are blocking errors when the parent or component
Part is missing or inactive, a Part contains itself, the quantity is not a whole
number from 1 to 2147483647, or a parent/component pair repeats in the file. Rows
that would complete a cycle (through other rows in the file or existing
definitions) are blocking errors too, and every row on a cycle is reported in the
same review. Other columns produce warnings and are not imported.

An import merges definitions: matching links are updated in place, new links are
added, and links not in the file are kept. Nothing is removed. A row that changes
an existing link's quantity shows a warning naming the old and new quantity, so the
review shows exactly what an update changes. Stock, History and persisted shipment
snapshots are never changed: the service writes only BOM links and no ledger rows.

Confirm the changes using the checkbox, then **Commit BOM import** (an operator name
is required, as for every import kind). Python rereads the file, rejects changed
bytes, validates again against current definitions and Parts (a cycle or
deactivation made after review makes the commit stale and needs a new selection),
and then verifies a pre-import backup before writes. Backup failure blocks the
import. The existing service writes all links in one database transaction, so a
database failure leaves every definition unchanged; the failure message says no
BOM definition changes were committed. A review is consumed when commit starts and
is never retried automatically; an ambiguous response locks the panel until the
operator checks the outcome.

Definitions are re-read whenever BOM, BOM explorer, Ship and Parts are opened, so
availability and Build capacity follow the imported definitions. Leaving Ship (the
only way to reach Settings) discards the on-screen shipment review, and a review
held by the bridge cannot confirm if the imported definitions change its leaf lot
allocation: the existing reviewed-plan check rejects it with `PLAN_CHANGED` and Ship
shows the updated allocation for a fresh review. A review whose allocation is
unaffected still ships exactly what the operator reviewed.

Known limitation: quantity-change warnings describe the definitions at review time.
If another operator edits a reviewed link before commit, the commit still writes
the quantities in the reviewed file (the bytes and validity are rechecked), but the
warning text from the review no longer describes the change; inspect the BOM page
afterwards. Only new blocking errors, such as a cycle or an inactive Part, are
surfaced as a stale review.
Historical shipment snapshots are stored per Lot and are not recomputed from the
current definitions.

The native smoke builds a disposable nested/shared assembly, drives real dialog
selection/cancellation, self-reference, quantity and cycle errors, warnings,
confirmation, changed-file rejection, duplicate clicks and lost-response recovery
with failed reads, checks the refreshed BOM page and Python-derived requirements,
rejects a shipment review made before the import, ships a fresh review, and verifies
that a later import leaves that shipment's snapshot unchanged. It reopens the store
and compares the definition and snapshot. Backup failure and database-failure
rollback are covered by public bridge tests rather than the native smoke.

## Restore and rollback (closed app only)

There is no in-app restore. To restore a backup:

1. Close the application (and the original application) so nothing holds the database.
2. In the folder holding the database (`data/` for source launch, or the folder of the
   `--database` file), move `inventory.db` **and** any `inventory.db-wal` and
   `inventory.db-shm` files to a safe place outside it. Keep them; moving them away
   also stops stale write-ahead files being applied to the restored database.
3. Copy the chosen `inventory-*.db` backup from that inventory's `backups/` folder into
   the database folder as `inventory.db`.
4. Start the application with that database and inspect Parts, Lots and History.

A backup contains only what had been recorded when it was made. Stock changes made
after that backup exist only in the displaced database: restoring an older backup
loses those transactions from the live ledger. Before resuming work, compare the
displaced database's History against the restored one and re-enter or reconcile each
receipt, shipment, move or count made since, through the normal workflows so every
balance change gets a ledger row. Never restore over a database you have not kept a
copy of. To undo a restore, close the app, set the restored files aside and move the
displaced database files back together.

## Deferred workflows

The shell directs operators to the original application for
location administration. Backup restoration requires closing the app as described above.
Global search is part search only.

Not yet validated: a macOS package and installers (Linux and Windows: [packaging](packaging.md)), human screen-reader review,
human operator acceptance, and performance/release hardening. The native smoke is
scripted desktop acceptance, including a rendered contrast/name audit, not an
exhaustive accessibility review (see the [accessibility record](acceptance.md#accessibility-review-record)). Mutation
reconciliation is operator-assisted, without durable request deduplication.
