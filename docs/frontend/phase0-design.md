# Phase 0 design decisions

Status: Phase 0 approved on 2026-09-30. Selected layout: A — Attention first.

This records decisions for the static visual prototype described in GUIDANCE.md.
The complete design was confirmed by the user. The standalone prototype was
reviewed and approved, with layout A selected for subsequent implementation.

## Visual verdict

The user preferred and approved A (Attention first). Use its attention/action-first
dashboard hierarchy, followed by compact summaries and recent activity, as the
design reference for the production frontend. Keep the approved shared workflows,
light-first theme, and remembered theme choice.

Variants B and C remain comparison artifacts in the throwaway prototype. Rewrite
the selected design to production standards during migration rather than promoting
the prototype directly.

Prototype primary source: branch `prototype/invsys-phase0`, based on main.
All three variations are retained there; A is the approved design reference.

## Confirmed decisions

- Balance fast repeated stock entry with Parts and BOM investigation.
- Review layouts at 1366 × 768 and 1920 × 1080. Smaller windows remain usable
  through scrolling, with critical actions reachable and no horizontal page scroll.
- Use a calm workstation style: subtle glass on navigation and overlays, opaque
  data tables, restrained indigo/cyan accents, and clear typography. Emphasize
  shortages and selected records.
- Use realistic fixtures and scripted interactions to rehearse search/filter,
  part inspection, receiving, standard/BOM shipment review, success, validation
  errors, and changed allocation review. Preserve existing rules in those scenarios.
- Keep the prototype standalone, without Python, pywebview, or database integration.
- Prioritize low-stock attention and Receive/Ship quick actions on the dashboard,
  followed by compact summaries and recent activity. Records open related workspaces.
- Inspect parts in an overlay drawer that preserves search, filters, selection,
  and scroll position. Details have an explicit Edit mode; contextual Receive,
  Ship, and Move actions open their dedicated pages.
- Use single-page Receive and Ship forms with persistent field labels and an
  adjacent stock-impact review, stacked below at smaller widths. Receive submits
  directly; Ship opens a confirmation showing the reviewed lot or BOM allocations.
- Keep an editable operator control visible in the header across all pages.
  Transaction reviews display that identity; request a name when a stock-changing
  action requires it.
- Start in light mode on first launch. Provide an obvious dark/light switch,
  remember an explicit choice, and review both themes during prototype acceptance.
- Retain transaction drafts during session navigation. Confirm before discarding
  unsaved part edits. Returning to a transaction requires reviewing current availability.
- Receive success retains part/location and clears quantity, lot, and reference,
  matching current behavior. Ship success shows the shipment number and an explicit
  Ship another action. Use persistent result feedback plus a toast; errors preserve
  input and appear near the relevant field or review section.
- Selecting a History record opens a read-only drawer with lot, locations,
  operator, reference, notes, and shipment/component links where applicable.
  Preserve table position and filters.
- Demonstrate BOM pan/zoom/fit, node selection, an inspector, and fixture-backed
  quantity/location scenarios. Defer subtree collapse, breadcrumbs, and BOM editing.
  Distinguish build-capacity warnings from shipment shortages.
- Fully demonstrate the required Phase 0 views. Move, Adjust, and Settings have
  clearly labeled preview layouts. Ctrl+K demonstrates fixture-based part search
  and navigation; broader command search remains a later-phase capability.

## Existing behavior to represent accurately

- Parts currently have number, description, minimum quantity, default location,
  and active state. Revision and category in guidance examples are not existing fields.
- Receive adopts the selected part's default location and requires a real lot number.
- Standard shipping distinguishes selected-lot availability from total location stock.
- BOM shipment allocation may consume one component from several lots. Changed
  allocations require another review, and shortages block the entire shipment.
- Part activity, part low-stock status, BOM build capacity, and shipment readiness
  are distinct concepts. Use separate text and indicators rather than one generic status.
- Existing BOM capacity thresholds are Critical at 100 or fewer final builds,
  Low at 101–500, and Ready above 500. These are separate from requested-quantity shortages.

## Required demonstration scenarios

- Healthy, low-stock, and inactive parts, plus an empty search result.
- Repeated receiving of lots, including missing-lot feedback.
- Standard shipping with sufficient total location stock but insufficient
  selected-lot stock.
- Nested BOM shipping with allocation across multiple lots, a shortage, and
  changed allocations requiring another review.
- History inspection with shipment and component traceability.
- Loading and error states, and returning to an unfinished transaction form.

Use scripted fixtures that preserve existing business rules. These demonstrations
are presentation scenarios rather than a second implementation of inventory logic.

## Visual acceptance gate

Before Phase 1 integration:

- The user approves required screens and demonstration flows in both light and
  dark themes at 1366 × 768 and 1920 × 1080.
- Keyboard navigation, drawer focus management and closing, readable tables,
  reachable actions, and reduced motion work.
- Smaller windows remain usable through scrolling without horizontal page scroll.
- Move, Adjust, and Settings are clearly marked previews.
- The prototype remains demonstrable without Python, pywebview, or database access.

## Next step

Proceed to Phase 1: prove pywebview loading, the narrow typed Python bridge, safe
errors, and packaged frontend assets. Layout A is the approved visual reference.
Retain the existing PySide6 application while migrating real workflows incrementally.

## Prototype verification

- Strict TypeScript checking and the Vite production build completed successfully.
- Browser smoke checks exercised receipt validation and reset, draft retention,
  standard selected-lot shortages, multi-lot BOM review, stale-allocation rejection
  and re-review, History traceability, and unsaved part-edit confirmation.
- Browser keyboard checks exercised Ctrl+K search, result activation, drawer focus
  trapping, Escape, and page shortcuts.
- Both themes and all three dashboard variants were checked for horizontal page
  overflow at the agreed desktop viewport settings and at 1000 × 650.
- Production output omits the development-only variant switcher.
- Python code and live inventory are unaffected. No production integration tests
  were added for this throwaway prototype.
