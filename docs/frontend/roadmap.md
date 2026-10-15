# Desktop frontend roadmap

The pywebview frontend is replacing the PySide6 screens one workflow at a time.
Both applications share one `InventoryStore` and one SQLite database. The PySide6
application stays until the frontend reaches agreed feature parity.

For delivered behavior, launch, and the bridge contract, see [desktop.md](desktop.md).
The approved visual reference is [layout A](phase0-design.md).

The [frozen capability register and executable acceptance fixtures](acceptance.md)
track every required migration workflow, deferred enhancement, native/operator
scenario, approved workload and retirement evidence gate from tickets #39/#40.

## Progress

| Phase | Goal | Status |
|---|---|---|
| 0 | Static visual prototype | Complete |
| 1 | pywebview + typed bridge, local assets, basic Linux package proof | Complete |
| 2 | Live Attention first dashboard and workspace links | Complete |
| 3 | Parts search/create/details, editing and deactivation/reactivation | Complete |
| 4 | Searchable immutable History and persisted shipment/component trace | Complete |
| 5 | Real lot receiving, drafts, refresh, and recovery | Complete |
| 6 | Move + Adjust | Complete |
| 7 | Standard and nested BOM review/shipment with recovery | Complete |
| 8 | Read-only BOM explorer with pan/zoom/fit delivered; subtree focus, breadcrumbs deferred | In Progress |
| 9 | Part search shortcut delivered; command search deferred | In Progress |
| 10 | Operator/theme, startup/manual backup, five CSV exports, folder access and Parts/Inventory receipt CSV import delivered; BOM CSV import deferred | In Progress |
| 11 | PySide6 retirement | Not Started |
| 12 | Scripted native/keyboard/layout acceptance delivered; release hardening deferred | In Progress |

Update this table when a phase meaningfully changes.

## Migration rules

- Migrate one workflow at a time, preserving tested behavior. Do not change
  inventory rules as a side effect of a UI migration.
- Python calculates stock, BOM structure, availability, allocation, and
  eligibility. The frontend never computes them or reads the database.
- Add narrow bridge use cases rather than generic data or settings access.
- Test each use case through the public bridge against real temporary SQLite.
- Usability and data readability take precedence over visual effects. Keep data
  tables and long forms opaque; reserve glass for navigation and overlays.
- Use the CSS tokens in `frontend/src/styles.css`; themes swap token values.
- Never communicate status by color alone. Keep visible focus, persistent labels,
  and `prefers-reduced-motion` support.

## Remaining phases

### 8. Interactive BOM Explorer

BOM authoring (add/update/remove direct components) is delivered on its own BOM
page; exploration below sits beside it and does not replace it.

Nested BOM graph with pan/zoom/fit, node selection, an inspector (required,
available, build capacity, locations, status, links to Part and History),
subtree collapse/focus, breadcrumbs, and a build quantity input. Distinguish
build-capacity warnings from shipment shortages. Python supplies graph truth;
graph interaction never mutates inventory. Large BOMs must stay responsive.

### 9. Command search

Extend Ctrl+K from part search to high-value actions (Receive/Ship/Move/View
history for a part), shipments, references, locations, and recent items. Keyboard
selection, Enter, Escape, and focus behavior must be predictable.

### 10. Settings, import/export, backup

Backup, latest-backup status, folder opening, the five CSV exports and reviewed
Parts and Inventory receipt imports are delivered in Settings (see `desktop.md`).
Expose the remaining BOM import through the same select → preview → row errors →
backup → commit lifecycle.
Never silently import malformed data. Include only meaningful settings.

### 11. PySide6 retirement

Before removal, classify every PySide6 capability (Dashboard, Parts, BOM,
Receive, Ship, Move, Adjust, History, Settings, import/export, backup, keyboard
shortcuts, lot behavior, BOM allocation) as Equivalent, Improved, Intentionally
changed, Not required, or Missing. Remove the old views, widgets, QSS, and launch
code only when nothing required is Missing and packaging works.

### 12. Hardening

Performance with large catalogs, histories, and BOMs; screen-reader and contrast
review; failure cases (database errors, missing files, failed imports, bridge
errors, stale state); Windows/macOS packaging and installers; human operator
acceptance.
