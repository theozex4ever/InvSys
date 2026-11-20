# Planned UI SDK integration

Status: planned pilot; no dependencies installed or application behavior changed.
This plan concerns [vercel-labs/ui](https://github.com/vercel-labs/ui), called
UI SDK, rather than shadcn/ui. The feasibility review on 2026-11-19 inspected
upstream commit `b4dbe88209ecf4dc555225f630268095f510ad49`. Findings are from
source and documentation, not an executed compatibility test.

## Purpose and scope

Improve Part and Lot selection in inventory forms without replacing the frontend
framework or inventory workflows. UI SDK supplies reusable keyboard, focus,
selection, popup and ARIA behavior. Its unstyled Web Components can use the
existing CSS tokens; React and Tailwind are not required
([Web Components introduction](https://ui-sdk.dev/docs/web-components)).

Start with one searchable Part picker in Receive. Show Part number and description,
keep the selected Part identifier separate from search text, and retain existing
eligibility and stock reads through the Python bridge. If the pilot passes the
checks below, expand the shared picker to Ship, Move, Adjust and BOM, then evaluate
searchable Lot selection where operators choose an existing Lot. Receive must
continue accepting a new Lot number.

Command search and keyboard navigation in a BOM outline are possible later uses.
Replacing working dialogs, drawers, native controls throughout the app, or the
BOM graph is outside the initial scope. UI SDK does not replace Python validation,
allocation, persistence, mutation recovery or the bridge contract.

## Integration approach

- Pin compatible exact versions of `@ui-sdk/web` and `@ui-sdk/core` after the
  pilot selects a release; update the npm lockfile. Upstream is explicitly beta,
  so upgrades need review and regression validation
  ([beta terms](https://github.com/vercel-labs/ui#beta-terms)).
- Statically import only required component entries into the existing Vite build.
  Preserve the local IIFE, relative assets and offline `file://` launch. Avoid the
  CDN/module autoloader. Inspect dynamic imports and emitted assets; bundling an
  offline IIFE is a proposed integration approach, not an upstream guarantee
  ([installation](https://ui-sdk.dev/docs/web-components/installation)).
- Put SDK value/event access behind a small shared picker interface. Adapt current
  native `select` value reads, option updates and disabled-state selectors. A
  pending, uncertain or completed workflow must lock the new control as before.
- Keep drafts and selected identifiers outside replaceable DOM. Prefer updating
  live picker properties over rebuilding it with `innerHTML`; replacement creates
  a new instance and can lose query, focus and selection.
- Bind SDK state events directly or use capture listeners: the documented state
  change events do not bubble. Check event timing and programmatic value updates
  against existing change handlers
  ([state and events](https://ui-sdk.dev/docs/web-components/state-and-events)).
- Keep existing theme tokens and status semantics. Account for custom-element
  form association, validation and reset behavior
  ([forms](https://ui-sdk.dev/docs/web-components/forms)).

## Pilot acceptance and expansion decision

1. Build and launch the packaged app offline on Linux, Windows and macOS. Verify
   Custom Elements and form-associated `ElementInternals` support in the actual
   embedded engines. Check popup positioning, dismissal and focus with native
   dialogs, including engines without the Popover API.
2. Measure final gzipped JS/CSS and inspect for external or module loads. The
   current JavaScript budget is 35,000 bytes in
   `frontend/scripts/check-dist.mjs`. Upstream's combobox budget is 52,965 bytes,
   which flags a likely budget conflict, but is not a measurement of incremental
   cost in InvSys. Record actual output before proposing a reviewed budget change
   ([upstream size budgets](https://github.com/vercel-labs/ui/blob/b4dbe88209ecf4dc555225f630268095f510ad49/size-budget.json)).
3. Exercise typing, arrow keys, Enter, Escape, Tab, labels, screen-reader semantics,
   empty/loading/error results, disabled controls and focus restoration in both
   themes. Preserve Ctrl+K and Ctrl+1–9 behavior.
4. Verify draft preservation across navigation and refresh, selected-value reset,
   stale-result suppression, and repeated DOM replacement while a popup is open.
   Changing a selection must invalidate shipment reviews as before. Pending and
   uncertain submissions must remain locked, with no automatic mutation retries.
5. Update native smoke tests and performance probes for changed controls while
   preserving their assertions. Use the existing large-catalog fixture and
   [packaged performance envelope](performance.md); verify bounded list rendering
   rather than assuming the component alone makes a large catalog responsive.
6. Run the repository CI workflow on the implementation commit and record its run
   link and packaged evidence. Expand only when compatibility, size, performance
   and workflow checks pass. If they do not, retain the existing controls and
   document the measured blocker before choosing another implementation.

The pilot is a bounded evaluation, not approval for a wholesale frontend rewrite
or an automatic increase to asset budgets. It introduces observable behavior and
must follow the existing [acceptance](acceptance.md) and
[sign-off](signoff.md) requirements when delivered.
