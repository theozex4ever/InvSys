# Working prototype acceptance — issue #10

Validated on 2026-10-02 for [#10](https://github.com/theozex4ever/InvSys/issues/10)
and the bounded workflow in [#6](https://github.com/theozex4ever/InvSys/issues/6).
This is a working desktop slice using approved layout A. The original PySide6
application remains available; the complete frontend migration is unfinished.

The subsequent 2026-10-04 presentation pass and its executed validation are
recorded in [frontend polish decisions](polish-decisions.md#validation--2026-10-04).

## Reproduce the review

From the repository root, use a virtual environment and the locked frontend:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt -r requirements-desktop.txt
npm ci --prefix frontend
npm run build --prefix frontend
python inventory_desktop.py --database /tmp/invsys-review/inventory.db
```

Choose a new disposable directory for each independent review. The explicit
database keeps logs and backups beside it. Opening an empty review database
creates locations but no fixture inventory. The regular launcher without
`--database` uses existing operational data and startup backups.

For a repeatable **native desktop** check with actual built assets and real writes:

```bash
QT_API=pyside6 QTWEBENGINE_CHROMIUM_FLAGS=--force-prefers-reduced-motion \
  python inventory_desktop.py --database /tmp/invsys-acceptance/inventory.db --smoke-check
# Repeat against the same disposable file to check restart reads/startup backup.
QT_API=pyside6 QTWEBENGINE_CHROMIUM_FLAGS=--force-prefers-reduced-motion \
  python inventory_desktop.py --database /tmp/invsys-acceptance/inventory.db --smoke-check
```

This requires a graphical Linux session, PySide6 Qt WebEngine, and a display
large enough for the requested desktop sizes. Do not set `QT_QPA_PLATFORM=offscreen`
for this command. `QT_API=pyside6` selects the installed backend when multiple
Qt bindings exist. The Chromium flag exercises the reduced-motion media query;
without it the smoke reports whether that preference was active.

Smoke performs real writes only to the explicit database, saves operator
`Desktop smoke` and theme `dark`, and sets up new nested/shared BOM definitions
through InventoryStore. Each run creates a fresh BOM and receives real material
lots. It injects read/transport failures around real bridge operations to
exercise recovery. It emits native captures to `smoke-captures/` beside the
database; no captures or databases are committed. The script closes its window,
reopens SQLite and verifies stock, operator/theme, both shipment types, and
component snapshots, including the shipment whose response was lost.

See [desktop packaging instructions](desktop.md#basic-package-proof) for the
one-directory PyInstaller proof. Run the bundled executable with an explicit
disposable `--database` and `--smoke-check`, then repeat it against that file.
This proves a basic local package path; it is not a release installer.

## Acceptance coverage and results

Executed on Linux with Python 3.14.7, PySide6 6.11.2, pywebview 6.2.1,
QtPy 2.4.3, PyInstaller 6.22.3, Node 26.10.0, and npm 12.2.0. The
existing lockfile and dependency requirements were unchanged.

| Area | Executed result |
|---|---|
| Public bridge with real temporary SQLite | **318 pytest tests passed** (15.64 s), including existing store, database, bridge, and offscreen Qt regressions. The new complete-journey test combines both shipment types, rejected receipts/shipments, stale allocation rejection/review, linked audit inspection, shipment numbering, and reopened-store equality. |
| Focused bridge journey/History/BOM | **36 passed** (4.85 s). No private serializer/ORM test seam or frontend test framework added. |
| Frontend | Strict `npm run check` and production `npm run build` passed; local HTML, JS, and CSS were present and nonempty. |
| Python checks | `ruff check .` and format checks on all changed Python files passed. |
| Source desktop | Real pywebview/Qt WebEngine smoke passed with built `file://` assets, the live bridge, no HTTP server, actual mutations, and reopened-database equality. |
| Basic packaged path | PyInstaller Linux one-directory build passed. The bundled executable passed the same full native smoke on its first and second launches using bundled assets. Launch without `--database` exited with the intended argument error. Optional driver/image-plugin build warnings remain; this is a workstation package proof, not a portable installer. |
| Startup backup | Repeated source and bundled native launches produced openable pre-launch backups. Public reads verified prior operator/theme, stock, and immutable transaction IDs. The second packaged launch retained first-run stock 19 in the backup, while the new database had stock 38 after the reviewed next-run entries. Existing backup collision/retention regressions passed in the full gate. |
| Refresh/navigation | Dashboard activity opens the matching immutable record; shipment success opens persisted consumption. Part details now open History with the part search and cleared type/page filters. Explicit History/catalog/dashboard refresh sees another operator's receipt and retains the relevant search. |
| Failure recovery | Missing lots, selected-lot shortage, BOM shortage, and changed allocations preserve entries without partial writes. Duplicate clicks submit once. Lost receipt, standard ship, and BOM responses preserve/lock drafts. A failed BOM reconciliation read leaves the draft locked; a subsequent read exposes persisted consumption and requires explicit verification, without retrying the mutation. |
| Native keyboard | Real Qt Tab/Shift+Tab/Escape checks passed in part, create, shipment review, and History dialogs, including visible focus, trapping, restoration, and drawer position. |
| Native layout | Five enabled pages and all four dialogs checked in light/dark at 1366×768, 1920×1080, 800×650, and 640×480. No horizontal page/dialog overflow; form labels and scrolling to critical actions checked. Wide data tables have their own horizontal scroll. Representative native captures visually inspected. |
| Reduced motion | Native Chromium forced preference matched the CSS media query; computed transitions were disabled. OS preference integration beyond that emulation was not tested. |
| Original application | The real PySide6 `app.main()` entry point launched with paths redirected to a disposable database; Dashboard, Parts, BOM, Receive, Ship, Move, Adjust, History, and Settings remained reachable. A startup backup retained received stock. |

The native checks are scripted desktop acceptance, separate from offscreen pytest.
They are not human operator sign-off or exhaustive accessibility review.
No browser automation framework or browser-only substitute was used.

## Integration fixes

Two native probes failed before their fixes: a failed History detail read offered
no retry inside its drawer, and a part drawer offered no contextual History
action. Both probes passed after implementing those actions. History retry uses
the same immutable transaction/shipment identifier and preserves drawer context;
late responses cannot replace a newer inspection. BOM recovery feedback
also now names automatic component lots instead of displaying an empty lot.

During validation, the UI probe needed native window activation, asynchronous
close-event handling, and completed paint frames before captures. Its reachability
check was corrected to allow independently scrolling tables and scrolling back
to a read-only drawer's close action. An initial package build with a relative
asset path and an external spec directory failed; an absolute source asset path
corrected it. These were validation harness/build issues, rather than inventory
failures.

## Two-axis review

Reviewed staged implementation against the task's starting commit
`48a051db263c73b2df3fb00d2dbea837a03ce098` using independent Standards and Spec
reviewers, before committing.

**Standards:** No hard violations. The public bridge/real SQLite boundary is
preserved, inventory rules remain in Python, no dependencies are added, and
acceptance limits are documented. One optional possible-Duplicated-Code
suggestion remains: the viewport tuple and resize stabilization appear in both
page and dialog checks in `desktop_smoke_ui.py`. A shared tuple could make later
viewport changes easier to coordinate. This is a maintainability suggestion,
rather than a documented-standard breach or blocker.

**Spec:** No findings. The changes cover the bounded real workflows, restart
persistence, navigation/retry, refresh, duplicate prevention, uncertain transport
reconciliation, native keyboard/layout checks, and remaining migration gaps.
No unasked scope expansion or incorrect implementation was identified.

Totals: Standards **0 hard violations, 1 optional smell** (duplicated viewport
matrix); Spec **0 findings**.

## Delivered milestones and remaining gaps

| Parent #6 milestone | Status |
|---|---|
| Bridge proof | Complete for this slice: typed real requests, safe errors, built local assets, basic Linux packaged path. |
| Complete inventory workflow | Complete for this slice: create/find, Receive, standard/BOM review and ship, History and durable consumption trace. |
| Operator validation | Complete scripted native workflow/keyboard/layout checks. Human operator usability acceptance remains deferred. |

The shell directs operators to the original application for Move,
Adjust, catalog editing/deactivation, location administration, BOM editing and
exploration, CSV import/export/BOM utilities, manual backup/restore, and operational
Settings. Header operator/theme preferences and automatic startup backup are live.
Global search remains part search, without broader command search.

Windows/macOS packages, installers, screen-reader review, human operator acceptance,
performance/release hardening, and PySide6 retirement remain deferred. Mutation
reconciliation is operator-assisted: no durable request deduplication or new
cross-process concurrency guarantee was added. No schema migration, inventory-rule
rewrite, history deletion, or fixture-backed active workflow was introduced.
