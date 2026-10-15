# Migration capability and acceptance baseline

Frozen against original screens and delivered frontend at `d6d9911` (2026-10-11).
Source: [migration spec #39](https://github.com/theozex4ever/InvSys/issues/39),
[baseline ticket #40](https://github.com/theozex4ever/InvSys/issues/40),
`inventory_control/ui/{views,main_window,bom_flowchart}.py`, `store.py`,
`bridge.py`, and the existing native smoke. This is a starting classification,
not retirement approval. Update each row with evidence as its replacement lands.
Python remains inventory authority; one TypeScript frontend with Qt WebEngine is
the accepted destination. No inter-frontend layer or schema migration is needed.

## Required capability register

Numbers identify parent user stories. Equivalent means delivered behavior preserves
required operation; Improved means it adds useful inspection or protection;
Intentionally changed means an explicit interaction/delivery decision;
Missing means required replacement or acceptance evidence remains absent.
Mixed rows identify their missing portions explicitly. All Missing portions block
retirement. API regression coverage does not establish operator/package acceptance.

| Stories | Original capability / required outcome | Classification at freeze | Replacement evidence / outstanding work |
| --- | --- | --- | --- |
| 1 | Complete inventory work in one application | Missing | Original remains fallback until gates pass |
| 2 | Dashboard active counts, Low stock, recent activity | Equivalent | `test_bridge_reads.py`; native dashboard smoke |
| 3 | Contextual Dashboard actions and selected Part | Improved | Native context links; actions for future workflows Missing |
| 4 | Parts search, active/inactive/Low stock filters, numeric sorting | Equivalent | Bridge reads and native catalog smoke |
| 5 | Create number, description, minimum, default Location | Equivalent | `test_bridge.py`, `test_bridge_reads.py` |
| 6 | Inspect totals and Lot/Location balances | Improved | Read-only drawer and bridge reads |
| 7 | Edit fields while Part number stays immutable | Equivalent | `test_bridge_part_edit.py`; native Part edit smoke |
| 8 | Deactivate/reactivate; stocked-Part confirmation; no deletion | Equivalent | `test_bridge_part_edit.py` (bridge requires `confirm_stock`); native confirmation smoke |
| 9 | Confirm discarding unsaved Part edits | Improved | Cancel and drawer close confirm; native Part edit smoke |
| 10 | Receive real Lot, quantity, Location, operator, reference, notes | Improved | Bridge stock tests; receipt Notes added to original form fields |
| 11 | Adopt default Location; efficient repeat receipt | Equivalent | Native smoke retains Part/Location and clears submitted fields |
| 12 | Selected-Lot standard shipment review | Improved | Bridge reviews distinguish Lot and Location stock |
| 13 | Recipient, carrier, tracking, reference, generated number | Improved | Bridge stock/history; explicit review and persistent result |
| 14 | Nested/shared leaf requirements and per-Lot allocations | Equivalent | Bridge BOM tests; native BOM smoke |
| 15 | Shortage/stale plan blocks until another review | Equivalent | Bridge reviews/BOM; native changed-plan smoke |
| 16 | Phantom assemblies consume leaves only | Equivalent | Workflow restart tests and native reopened-store checks |
| 17 | Move positive-stock Lot, source/destination, operator, reference | Equivalent | `test_bridge_move.py`, native Move smoke; reference is existing service metadata |
| 18 | Move source/destination before/after review | Improved | `preview_move` reports Lot and Location before/after for both Locations from one snapshot |
| 19 | Atomic paired MOVE_OUT / MOVE_IN | Equivalent | Store regression retained; bridge write-failure atomicity and restart tests; native Move smoke |
| 20 | Expected/count/difference, operator, required reason | Improved | `test_bridge_adjust.py`; native Adjust smoke. Python supplies expected/difference; stale expected count and lost responses need another review/reconciliation |
| 21 | Adjust existing zero-stock Lots | Equivalent | `test_bridge_adjust.py` found-stock case; native Adjust smoke counts a zero-stock Lot |
| 22 | Large-correction confirmation threshold | Equivalent | Threshold boundaries in `test_bridge_adjust.py` (increases/decreases); native confirm/cancel smoke |
| 23 | BOM direct component add/update/remove | Equivalent | `test_bridge_bom_authoring.py`; native BOM authoring smoke |
| 24 | Reject self-reference, cycles and invalid quantities | Equivalent | Store tests retained; bridge authoring tests; native rejection smoke preserves the draft |
| 25 | Existing component updates quantity; confirm removal | Improved | Adding an existing component updates it without row selection; removal needs bridge `confirmed` and a native dialog |
| 26 | Nested graph pan, zoom, fit | Equivalent | BOM explorer; `test_bridge_bom_explore.py`; native explorer smoke |
| 27 | Location/quantity availability and shortages | Equivalent | `explore_bom` bridge tests; native explorer smoke |
| 28 | Shared leaves aggregated in Build capacity | Equivalent | `explore_bom` shared-leaf bridge test |
| 29 | Critical <=100, low 101–500, separate from shortage | Equivalent | Boundary and separation bridge tests; native explorer smoke |
| 30 | Search/page immutable History; exact record inspection | Missing | Paging and record/shipment drawers Improved; original Notes, Location, timestamp and transaction-type text search plus column sorting Missing; A16/A17 block retirement |
| 31 | Historical per-Lot consumption survives definition edits | Improved | Bridge History and acceptance fixture restart tests |
| 32 | Export Parts, Inventory, Transactions, Shipments, BOM | Equivalent | Settings per-kind exports reuse the service fields, Lot trace and persisted shipment summaries; `test_bridge_export.py`, native CSV/file/failure and keyboard smoke |
| 33 | Select/preview three CSV import kinds; row errors/warnings | Improved | Parts, Inventory receipts and BOM delivered: real-file bridge tests and native dialog smoke. BOM adds ignored-column and quantity-change warnings, preview-time inactive-Part and quantity-limit errors, and reports every cycle row in one pass |
| 34 | Explicit confirmation, commit validation, pre-write backup | Improved | All three kinds delivered with unchanged service transaction boundaries (BOM links write in one transaction), digest and current-state revalidation (cycles, inactive Parts) and a verified backup taken before writes |
| 35 | Import outcome and refreshed screens | Equivalent | All three kinds: counts/backup path, refreshed catalog/dashboard/details/History/latest backup and locked recovery; BOM, BOM explorer and Ship re-read definitions when opened and a shipment review made before an incompatible import is rejected |
| 36 | Startup/manual backups, latest metadata, retention | Equivalent | Settings Create backup and latest/count status; startup backup and retention 20 retained; `test_bridge_utilities.py`, native smoke |
| 37 | Open selected-database export/backup folders | Equivalent | Settings folder buttons through the launch-selected context and native opener; failures reported; real file-manager launch on Windows/macOS Missing (smoke records the Linux request) |
| 38 | Closed-app restore and rollback | Intentionally changed | Procedure below; no in-app restore; rehearsal Missing |
| 39 | Remember operator and theme | Improved | Bridge preferences/restart; original remembers operator only |
| 40 | Keyboard destinations, focus, themes, small windows | Missing | Ctrl+K delivered; Ctrl+1–9 destinations absent; native theme/layout smoke retained |
| 41 | Preserve drafts during navigation and recoverable failure | Improved | Native drafts/recovery smoke; future forms require coverage |
| 42 | Duplicate-click prevention; lock uncertain submissions | Improved | Native double-submit/lost-response checks |
| 43 | Authoritative recovery; failed reads retain lock | Improved | Native recovery UI checks, bridge stock/history reads |
| 44 | Readable validation/stale/file/database errors | Missing | Delivered bridge safely handles errors; utilities cases remain |
| 45 | Offline standalone Windows/Linux/macOS bundles | Missing | Source/native smoke and Linux proof are insufficient |
| 46 | Explicit packaged database; source defaults preserved | Equivalent | `test_desktop_launcher.py`; actual three-platform package evidence Missing |
| 47 | Approved workloads meet response limits | Missing | Executable large fixture below; no reference-machine timings yet |
| 48 | Copied-data upgrade and restart | Missing | Synthetic restart proven; representative copied-data rehearsal needed |
| 49 | Operator sign-off and all-platform acceptance | Missing | Evidence record below; no sign-off inferred |
| 50 | Remove old screens/launcher/tests/docs after acceptance | Missing | Blocked by every retirement gate |

## Original interaction contract

The original has grouped Catalog (Parts/BOM), Stock (Receive/Ship/Move/Adjust),
Dashboard, History and Settings. Ctrl+1–9 destinations are respectively Dashboard,
Parts, BOM, Receive, Ship, Move, History, Settings, Adjust. Ctrl+K focuses/selects
global Part search; Enter opens Parts and selects an exact match. Navigation focuses
each view's primary input (Adjust focuses its Part). Dashboard low-stock entries
open Parts; recent activity opens History with that Part. The new Ctrl/Cmd+K opens
Parts search; record links now inspect exact transactions. Preserve the numbered
destinations in the replacement; do not mistake the current shortcut gap for an
approved deletion. Escape closes new dialogs; Tab/Shift+Tab must stay inside,
and closing returns focus to the opener.

Original blank operator blocks mutations, focuses the operator input and asks for a name; last operator is persisted on edit.
Parts form minimum defaults to 0; Location starts at the first active Location
(normally Receiving). Number and description are required; selected Part number
is disabled while description/minimum/Location are editable. Stocked deactivation
asks Yes/No, default No; reactivation and empty-stock deactivation do not prompt.
Original selection/navigation does not confirm dirty Part edits: the parent adds
that protection deliberately. PartCombo lists eligible active Parts.

Receive starts at Stock, then adopts selected Part's default Location. Quantity,
Lot and reference start blank; quantity is positive; Lot is required and normalized
by Python. Preview is Location total, not selected-Lot stock. There is no receipt
confirmation. Success retains Part/Location and clears quantity/Lot/reference;
new receipt Notes follow the same clearing rule. Failures retain input, show readable
feedback/toast and do not mutate inventory. Original Receive has no Notes field;
Notes exist in the service and are exposed in the new form.

Ship starts at Stock then adopts Part default. Standard Lot dropdown contains only
positive-stock Lots at that Location and preserves the selection when possible.
Quantity/recipient/carrier/tracking start blank. Recipient is required. Original
form has no custom reference field; the service and replacement expose it. Standard
preview shows selected-Lot available/remaining. BOM hides parent Lot, displays
aggregated requirements and deterministic positive-Lot allocation in Lot-number
order; shortage or ineligible component disables confirmation. Both modes confirm
Yes/No (default No) with Part, quantity, Location, recipient and Lot/allocation.
Stale allocation rejects all writes and refreshes review. Original success clears
quantity/recipient/carrier/tracking and shows shipment number; replacement's explicit
Ship another keeps the successful result inspectable. Parent/intermediate balances
are unchanged; consumption snapshots are immutable.

Move starts source Stock/destination Shipping Bench then adopts Part default for
source. It offers positive-stock Lots only, retains Lot where possible, previews
selected-Lot source remainder, rejects same Location/shortage, and has no extra
confirmation. Success clears quantity and retains selection. Original form exposes
no reference, though the service supports it. Replacement must retain service
metadata and show both Locations before/after.

Adjust starts Stock then adopts Part default, offers existing Lots including zero
stock at that Location, previews expected/count/difference, and requires reason.
Count/reason start blank; count >=0. Additional Yes/No confirmation (default No)
occurs when `abs(counted - expected) >= max(10, expected // 2, 1)`.
Examples: expected 0: differences 9/10; expected 21: 9/10; expected 40: 19/20.
Test just below and exactly at each threshold, cancellation, and decreases too.
Success clears count/reason, retains selections, records COUNT_CORRECTION with
reason as reference; no-op count remains auditable.

BOM authoring starts quantity-per 1, Location Stock, requested builds 1. Select
parent to inspect direct children and nested flowchart. Selecting a child loads
quantity for update; original UI rejects an existing child entered without selecting
its row, while `add_bom_component` updates an existing link. Parent requires that
service update behavior in the replacement. Remove asks Yes/No (default No), leaves
inventory/history intact. Reject self/cycle/nonpositive quantity, show readable
toast, preserve definition. Graph supports drag pan, wheel/button zoom and fit.
Capacity warnings are critical <=100, low 101–500, otherwise healthy; shortage is
computed for requested builds separately. Shared leaves count once in aggregated
requirements, even when shown at multiple paths.

History defaults to all types/blank search and permits clear filters. Original
case-insensitive substring search covers timestamp, transaction type, Part, Lot,
source Location, destination Location, operator, reference and Notes (even though
Notes are not a table column). The immutable table shows the first 1,000 matches
and permits ascending/descending sorting on all nine columns: Time, Type, Part,
Lot, Qty, From, To, Operator and Reference; signed Qty sorts numerically.
Replacement adds paging and exact record/shipment drawers, persisted consumption
and context links. Its text search currently covers only Part, Lot, operator,
reference and shipment number; the separate exact-type filter does not preserve
transaction-type substring search. Records have fixed descending transaction-ID
order and no column-sort controls. Notes, both Locations, timestamp and type text
search, and all original column sorting are **Missing**, with no approved
intentional change; A16/A17 must pass before retirement.
Settings selects Parts/Inventory/BOM CSV, ordinary cancel makes no mutation;
preview shows row/level/field/message, blocks invalid input, then confirms import
(default No), revalidates and backs up before writes. Preserve actual per-kind
failure boundaries: do not promise new all-or-nothing import semantics. Export All
writes five CSV kinds; backup shows latest metadata and uses retention 20. Folder
buttons open exports/backups. Startup backup runs before opening an existing DB.
Use launcher-selected paths; report file/backup failures without claiming success.

## Explicitly excluded enhancements

These are **Not required**, not Missing parity: location administration (no original
screen/public API), broad command search (actions/shipments/references/Locations/recent
items), advanced graph inspector/subtree focus/collapse/breadcrumbs, in-app restore,
persistent packaged database picker, silent relocation, schema redesign, durable
request IDs/deduplication/automatic mutation retries, signed installers/wrappers,
auto-update, release publication/credentials/infrastructure, barcode/recent-Part
features, serial/expiry tracking, purchase/sales orders, supplier/customer databases,
role-based login, cloud sync, carrier integrations and labels. Do not implement
these through baseline acceptance. Basic graph pan/zoom/fit, standalone bundles,
and operator-assisted recovery remain required.

## Executable disposable inventories

Run `python -m inventory_control.acceptance` (workflow) or add `--large`.
The CLI emits the new database path and exposes no existing-database argument.
It creates a fresh OS temporary workspace with `fixture/inventory.db` and
`manifest.json`; keep that path for review. Programmatic `create_fixture(directory)`
requires a nonexistent directory, failing before writes if it exists. Failed builds
have no manifest: retry in a fresh directory. No ORM inserts or operational defaults
are used. Generated timestamps/shipment dates vary; content, quantities and counts
are repeatable. Manifest records profile/version, actual counts and shipment IDs.
Backups, logs and smoke captures from explicit desktop launch stay beside this DB.

Workflow fixture starts with 5 Parts, 15 transactions and 2 shipments:

| Part | Stock after baseline | Purpose |
| --- | --- | --- |
| STANDARD | Stock A=10, B=6, ZERO=0; Shipping Bench B=2 | Standard shipment, multi-Location/Lot, zero-stock correction; default Receiving |
| KIT | PARENT=10 | Phantom root; KIT→SUB×2 and KIT→LEAF×1 |
| SUB | INTERMEDIATE=10 | SUB→LEAF×3; shared LEAF totals 7 per KIT |
| LEAF | A=0, B=21 | Baseline KIT shipment consumed A=5/B=9; low stock boundary scenarios |
| INACTIVE | HELD=4 | Inactive catalog state with retained stock/history |

Operator `Acceptance operator`, dark theme, opening receipt Notes, Move reference,
count reason and standard/BOM carrier/tracking/reference are persisted. Use manifest
shipment IDs for History. Standard baseline shipment is 2 from A; BOM shipment is
2 KIT. Every generated balance has real ledger activity, including zero-stock Lot.

Large adds exactly 10,000 total Parts, 100,000 total transactions, and a separate
1,000-node expanded tree rooted at PERF-ROOT. Ten-way branching uses parent index
`(child_index - 1) // 10` for children 1..999 (root index 0); 900 leaves, depth 3,
unit edge quantities. First 1,000 nodes must be eligible. Other catalog entries
include inactive Parts. Receipt history distributes across all 900 leaves and three
Lot names with distinct PERF-RECEIPT references. The small KIT still exercises
nested/shared-path semantics; the large tree measures breadth, not recursion depth.
Generation may take minutes because it uses real public inventory operations;
fixture construction is excluded from UI response timings. Run large-fixture test
with its explicit 600-second bound; ordinary tests retain the existing 60-second bound.

## Repeatable native and operator scenarios

For each scenario, use a fresh workflow fixture unless specified, record starting
manifest and final authoritative stock/history, and reopen to verify persistence.
Run native automation with the exact production assets (not a dev server):

```bash
python -m pytest tests/test_acceptance.py tests/test_bridge_workflow.py
npm ci --ignore-scripts --prefix frontend
npm run build --prefix frontend
npm run check:dist --prefix frontend
python -m inventory_control.acceptance
# Paste the emitted path into both commands; this is disposable inventory.
python inventory_desktop.py --database /tmp/invsys-acceptance-REPLACE/fixture/inventory.db --smoke-check
python inventory_desktop.py --database /tmp/invsys-acceptance-REPLACE/fixture/inventory.db --smoke-check
```

The native probe adds DESKTOP-* scenarios through public operations on this
fixture. It independently asserts its own resulting stock/trace through a reopened
store and captures themes/sizes/keyboard dialogs. Existing acceptance records must
remain inspectable; manifest starting counts no longer describe the mutated file.
Do not replace smoke registration or lower any gate. Native runtime prerequisites
and platform bundle commands are in [desktop.md](desktop.md).

| ID | Operator actions and required observation | Present readiness |
| --- | --- | --- |
| A01 | Dashboard counts and initially empty Low stock; open LEAF from Parts; search STANDARD, filter INACTIVE, numeric sort, inspect all balances; create unique Part then duplicate error | Delivered, bridge/native coverage |
| A02 | Receive STANDARD: default Receiving; choose Stock/NEW, qty 3, reference ACCEPT-NEW, Notes; blank Lot/invalid qty reject unchanged; success repeat-entry; leave/return preserves unsent fields | Delivered, native/API |
| A03 | Ship STANDARD A: qty 11 rejects despite Location total 16; qty 2 confirms correct Lot remainder 8; cancel no writes; inspect number/recipient/carrier/tracking/reference and History | Delivered, API/native |
| A04 | Ship KIT qty 4: shortage; qty 2: leaf requirement 14, B allocation 14, parent/intermediate unchanged. Review then receive LEAF Lot 0 to force changed allocation; old confirmation rejects without writes; explicitly review and confirm again | Delivered, API/native |
| A05 | Inspect baseline BOM shipment A=5/B=9; change SUB→LEAF from 3 to 4; restart; old trace still A=5/B=9. Search manifest shipment number, reference, Lot/operator; page/type/filter; close drawer retains selection/scroll/focus | Delivered, bridge/native coverage; edits through BOM page |
| A06 | Edit STANDARD description/min/default without number change; dirty navigation cancel/discard; deactivate stocked INACTIVE after reactivation: cancel then confirm; history retained and ineligible stock actions reject | Delivered edit/active replacement: `test_bridge_part_edit.py` and native Part edit smoke; operator/package runs remain future gates |
| A07 | Move STANDARD B 2 Stock→Shipping Bench: source 6→4, destination 2→4; same Location/qty 7 reject unchanged; one paired transaction; chosen Lot, operator/reference retained; restart | Delivered, bridge/native coverage |
| A08 | Count STANDARD ZERO 0→3 with reason; blank reason rejects; counts just below/exact large thresholds above, both directions; cancel no writes; confirm one COUNT_CORRECTION; zero Lot remains selectable | Delivered, bridge/native Adjust coverage; original safety tests retained |
| A09 | Author KIT direct links; add existing link updates; confirm/cancel removal; reject self/cycle/zero/negative; inspect nested/shared tree Location/quantity, pan/zoom/fit; capacity 100/101/500/501 distinct from shortage | Replacement Missing |
| A10 | Export all five kinds, retain headers/Lot/trace. Select all three import kinds: valid, invalid, warning, cancel, changed input before commit, commit-time stale state; confirm backup exists before write; inspect actual per-kind failure outcome and refresh | Export replacement delivered: public bridge real-file tests and native CSV acceptance; Parts, Inventory receipt and BOM import replacements delivered (bridge tests and native smoke); real-file service regressions retained |
| A11 | Manual backup/status/retention; open selected DB's export/backup folders; failed file/backup reports error, no fabricated success; source default/INVSYS_HOME and override; standalone requires explicit DB | Backup/folder replacement delivered (bridge tests, native smoke); real file-manager evidence on three platforms Missing; launcher regressions retained |
| A12 | Navigate with Ctrl+1–9/Ctrl+K and contextual links; all dialogs keyboard-only; visible focus, both themes, reduced motion, 640×480 actions reachable by scrolling; screen-reader labels and non-color status/contrast review | Native checks delivered, numbered shortcuts and human review Missing |
| A13 | Double-click each mutation; simulated committed/lost response and unsent response preserve draft/lock. Failed recovery read remains locked; authoritative reads show exact Lot/operator/metadata; explicit completion/absence decision only; never auto-retry | Native delivered stock checks; future mutation coverage Missing |
| A14 | Rehearse upgrade on a copy of representative pre-migration DB; compare Parts/Lots/balances/ledger/shipments/BOM snapshots before/after launch and restart; closed-app backup restore on a separate copy; record reconciled rollback | Copied-data/operator evidence Missing |
| A15 | Each platform's standalone offline bundle, selected DB, two native runs, no HTTP/dev server, correct assets, startup backup, retained metadata/restart; all performance scenarios below | Three-platform package evidence Missing |
| A16 | On a fresh workflow fixture, History text search `Disposable baseline` returns 8 receipt records; `Shipping Bench` returns both Move records; `MOVE_` matches MOVE_OUT and MOVE_IN without selecting a type; the baseline timestamp date matches all 15 records. Verify case-insensitive matching, source/destination Location searches, combination with exact-type filter and Clear filters; all records remain immutable | Replacement Missing: these current Notes, Location, timestamp and type text searches return zero; existing Part/Lot/operator/reference/shipment search remains required |
| A17 | On a fresh workflow fixture, sort History ascending then descending by Time, Type, Part, Lot, Qty, From, To, Operator and Reference. Qty ascending starts at -9 and descending at +30, with signed numeric ordering; other columns follow displayed values. Verify the same matching record set and unchanged ledger after sorting, filtering, drawer inspection and restart | Replacement Missing: fixed descending-ID order and no column-sort controls |

Future native checks extend the retained smoke at workflow boundaries. API tests
use real temporary SQLite and observe success/error, unchanged state on rejection,
paired ledger rows, stored trace and restart. Never assert private helper calls or
replace original widget safety tests before replacement coverage exists.

## Performance definitions and reference machines

Approved targets: 10,000 Parts, 100,000 transactions, 1,000 expanded BOM nodes.
Use the large fixture, exact commit/profile version, pristine copy per repeat,
production standalone bundle and a designated representative workstation for each
of Windows/Linux/macOS. Record CPU model/core count, RAM, disk type, GPU, OS build,
display scaling/resolution, power mode, Python/Qt/WebEngine/runtime versions,
bundle/asset hashes, fixture DB hash and manifest, database path/storage, background
load and cache condition. Operator or integration owner designates machines;
this baseline does not invent approval or treat a development container as one.

Use monotonic elapsed time and capture action-to-usable-render evidence (instrumented
UI timestamps or timecoded recording); backend call latency alone is insufficient.
Exclude fixture generation. Run one warm-up then five measured repeats per scenario,
and a separate cold launch after process exit. Retain every raw timing, min/median/max,
failures and correctness assertions; do not hide slow repeats in averages. Each
measured run must meet its target; document cache condition rather than claiming
unmeasured cold-cache behavior.

| ID | Start | End and correctness | Target |
| --- | --- | --- | --- |
| P01 | Submit catalog search PERF-00999, then clear/apply active/inactive and sort | Correct rows/state rendered, actionable drawer/buttons and visible focus | <=2 s per interaction |
| P02 | Submit History search PERF-RECEIPT-050000; clear then Next page/type filter | Correct record/50-row page rendered, filter/page controls actionable; exact record opens | <=2 s per interaction |
| P03 | Request standard STANDARD/A review qty 2; BOM KIT qty 2 and PERF-ROOT qty 1 | Authoritative selected-Lot/leaf allocation rendered and confirmation usable; no writes from review | <=2 s per review |
| P04 | Open PERF-ROOT explorer at Stock for one build | All 1,000 expanded nodes laid out; pan/zoom/fit usable; 900 aggregated leaves, correct capacity/shortage | <=5 s |
| P05 | Start standalone executable with explicit large DB | Initial authoritative dashboard rendered; navigation and input usable, no pending startup overlay | <=10 s |

The large tree is a frozen fixture shape, not a universal claim about all possible
BOMs. KIT covers shared requirements separately. Screenshot or a logged promise
of future benchmark work does not establish response-time acceptance. Missing
explorer/package functionality means P04/P05 await those tickets.

## Evidence and retirement record

For every A/P scenario, record: scenario ID, capability/story IDs, commit, fixture
version/hash and initial state, platform/bundle hashes, hardware record ID,
commands or exact operator steps, UTC execution date, expected/actual outcome,
authoritative before/after reads, raw timings, logs/capture locations and
pass/fail/not-run with reason. Keep records with the release evidence and update
this checklist; raw disposable databases/captures need not enter Git. Human records
include operator identity/role, intended workstation, explicit acceptance/date,
accessibility/contrast observations and unresolved objections. Scripted smoke is
not human sign-off. No unchecked gate is waived by an Improved classification.

Retirement requires all of:

- No Missing required capabilities, with evidence for their actual replacements.
- Existing lint/format, strict mypy/TypeScript, randomized warning-clean tests and
  >=85% branch coverage; asset size/reproducibility, security/dependency and CI gates.
- P01–P05 results on designated machines, not isolated store benchmarks.
- Copied-data upgrade/restart, preserved immutable trace, backup/restore rehearsal.
- Windows, Linux and macOS actual standalone package acceptance, twice-run native
  smoke against their exact built assets, source and packaged path behavior.
- User/designated-operator sign-off plus recorded screen-reader/contrast review.
- After removing original UI, repeat relevant automation and package checks;
  remove only tests/dependencies that no remaining runtime behavior needs.

Cutover/restore rehearsal: close both apps, verify a backup, copy existing inventory
for acceptance, install the accepted bundle, explicitly select the intended DB,
validate representative reads, then resume work only after approval. For restore,
close the app and copy a verified backup over a disposable test inventory; keep the
displaced DB and any WAL/SHM sidecars together outside the restored path, then reopen
and compare authoritative records. Retain the last known-good release artifact.
Rollback must reconcile any ledger activity written since the backup; never overwrite
later transactions with an older backup as an unexamined recovery action. Restore
remains operator-assisted and closed-app; no new restore API is introduced.

## Ticket 40 execution evidence

Populate with commands actually run at implementation time. This baseline establishes
fixtures and repeatable scenarios; it does not claim future performance, package,
accessibility or operator approval. Coordinate future changes with one integration
owner for navigation/API/launcher/smoke/styles/CI/locks. Use separate worktrees and
merge one change at a time; one workflow lane alongside packaging is the default.

Executed on 2026-10-11 on this Linux development workstation (Python 3.14,
locked toolchain in `/tmp/invsys-ticket40-venv`; not a designated performance or
package reference machine):

- Workflow fixture regression: passed through bridge/store against temporary SQLite,
  including baseline audit state, receipt/standard/BOM operations, historical trace
  after definition edit, restart and refusal to touch an existing directory.
- Strict mypy, Ruff lint/format, TypeScript checking, production frontend build and
  self-contained asset/size checks: passed. No dependency/CI threshold changes.
- Source native smoke twice on `/tmp/invsys-ticket40-native-xltgt57l/fixture/inventory.db`
  with Qt/PySide6 and forced reduced motion: passed. Included real reads/writes,
  confirmations/shortages, changed plans, drafts, duplicate clicks, ambiguous response
  and failed-read recovery, History, native focus/keyboard, themes/sizes, reopened
  persistence and absence of HTTP server. Two startup backups and 72 captures are
  beside that disposable DB. Existing baseline audit records were not replaced.
- Full randomized `python -m pytest --cov`: 372 passed in 218.94 seconds;
  total branch-aware coverage 85.66%, above the unchanged 85% floor. Includes the
  corrected large fixture: exactly 10,000 Parts, 100,000 transactions, 1,000 expanded
  BOM nodes, 900 eligible stocked leaves, three Lots per tested leaf and ready review.
  Full-run log: `/tmp/invsys-ticket40-full-tests.log`.
- Independent Standards and Spec reviews against approved starting commit `d6d9911`:
  no actionable findings.
- Follow-up PR review identified omitted original History capabilities. They are now
  classified Missing under story 30 with retirement scenarios A16/A17. On a fresh
  disposable fixture, original History matched Notes/Location/type/date searches
  with counts 8/2/2/15; replacement matched zero for each. Original signed Qty sort
  started at -9 ascending and +30 descending. No replacement History behavior was
  changed; these remain required migration work.

These source checks do not establish standalone Windows/macOS/Linux package
acceptance, designated-machine timings, copied operational-data rehearsal, or
human accessibility/operator sign-off. Those remain explicit retirement gates.

### Ticket #47 source validation — 2026-10-13

- Public bridge/CSV/backup/launcher tests: 80 passed using temporary SQLite and files.
- Full randomized coverage suite: 578 passed in 263.90 seconds; coverage 86.42%
  against the unchanged 85% floor. Log: `/tmp/invsys-issue47-full-tests.log`.
- Ruff lint/format, strict mypy, TypeScript checking, production build and offline
  bundle/size checks passed with the locked toolchain; dependencies are unchanged.
- Two successful source native runs on Linux/Python 3.14/Qt 6.11.2 against
  `/tmp/invsys-issue47-native-Ip7fMb/selected inventory/inventory.db`: all five CSVs,
  real file failures, destination and trace checks, duplicate clicks, navigation,
  both themes, minimum-size keyboard exports, restart and no HTTP server passed.
  CSVs, captures and successful `run2.log`/`run3.log` remain beside the disposable
  inventory. The first run exposed a smoke-probe function-serialization error,
  corrected before those two successful runs. Folder opening used the recording host.
- Independent Standards and Spec reviews against starting commit `4e8b4ae` found
  no actionable findings. Platform packages and operator acceptance remain pending.
