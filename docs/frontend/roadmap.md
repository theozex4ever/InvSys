# Desktop frontend roadmap

The pywebview frontend is replacing the PySide6 screens one workflow at a time.
Both applications share one `InventoryStore` and one SQLite database. The PySide6
application stays until the frontend reaches agreed feature parity.

For delivered behavior, launch, and the bridge contract, see [desktop.md](desktop.md).
The approved visual reference is [layout A](phase0-design.md).

## Progress

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

### 3. Parts editing

Add part editing and deactivation (`active = False`, no hard deletes). Confirm
before discarding unsaved edits.

### 6. Move and Adjust

Separate experiences that may share components.

- **Move**: part, lot, source, destination, quantity, with a before/after
  preview for both locations. Python keeps the atomic `MOVE_OUT` + `MOVE_IN`.
- **Adjust**: part, lot, location, expected and counted quantity, difference,
  and a required reason. Python creates the authoritative transaction.

Exit: moves stay atomic, no negative stock, lot and reason behavior and
transaction records match the PySide6 workflow, and balances refresh.

### 8. Interactive BOM Explorer

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

Expose the existing Python implementations: export parts, inventory,
transactions, shipments, and BOM; import with select → preview → row errors →
backup → commit; create backup, open its location, and show the latest backup.
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
