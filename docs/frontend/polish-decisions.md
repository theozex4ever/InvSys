# Frontend polish decisions

Status: design confirmed and implemented on 2026-10-04.

## Accepted scope

Polish the delivered Dashboard, Parts, Receive, Ship, and History pages, including
their dialogs and drawers. Address contrast, feedback, dashboard actions,
stock-impact reviews, and keyboard validation. Deferred workflows retain their
existing scope.

Use the approved Attention first layout A and the calm workstation aesthetic
recorded in [Phase 0 design decisions](phase0-design.md). Restore action tiles,
stock meters, summary icons, contextual Receive buttons, and distinct activity
styling for supported workflows. Use real inventory data and adapt the reference
to the delivered feature scope.

## Stock-impact reviews

Receive emphasizes stock at the selected Location: before, quantity added, and
expected balance after receiving. Standard Ship emphasizes the selected Lot's
stock at that Location: before, quantity shipped, and remaining balance; total
Location stock is secondary. BOM Ship emphasizes component requirements,
shortages, and Lot allocations rather than suggesting parent stock is consumed.

Label preliminary estimates as previews. Python remains authoritative for
validation and submissions; preserve the reviewed-shipment confirmation flow.

## Inventory health and operation readiness

Use amber for Low stock. Add explicit "No stock" text when a low-stock Part has
zero total stock. Retain the existing positive-minimum rule for Low stock.
Reserve red for shortages that block a requested shipment and for errors.
Inventory health and shipment readiness remain separate concepts.

## Confirmed scope

- Improve light-theme text contrast and control discernibility.
- Restore supported dashboard action tiles, contextual Receive controls, stock
  meters, summary icons, distinct activity styling, and consistent access to the
  Low stock filter.
- Normalize toolbar, help, and toast typography; give persistent success results
  a coherent visual treatment and use concise toast copy.
- Implement the agreed stock-impact emphasis and health/readiness treatment.
- Shorten migration notices into task-oriented instructions while preserving
  discoverability of workflows available in the original application.
- Restore modest state transitions consistent with the approved prototype and
  guidance, respecting reduced motion.
- Verify both themes at 1366×768 and 1920×1080, smaller-window usability, relevant
  real-bridge workflows, and native keyboard focus/closing/restoration. Resolve
  or explicitly report the focus validation failure found during the audit.

The user confirmed this scope after the design interview.

## Documentation boundary

These are reversible presentation decisions, so they do not warrant an ADR.
The existing glossary definitions of Part, Lot, Location, Stock balance, and Low
stock remain applicable; no new domain term has been agreed.

## Validation — 2026-10-04

- Strict TypeScript checking and production asset build passed.
- The existing suite passed: 331 pytest tests. Ruff checks and formatting checks
  on the changed Python smoke files passed.
- Complete source desktop smoke passed twice against the same disposable SQLite
  database with actual file-based production assets and the real Python bridge.
  Both runs checked five pages and four dialogs in light/dark at 1366×768,
  1920×1080, 800×650, and 640×480; no page/dialog overflow, persistent form labels,
  and reachable actions passed.
- Native Tab/Shift+Tab/Escape, visible focus, focus restoration, reduced motion,
  stock workflows, uncertainty recovery, and restart persistence passed. The
  earlier focus failure was in the smoke harness after viewport resizes; it now
  restores native focus immediately before its key probes.
- New real-bridge presentation checks verify contextual Receive navigation,
  receipt preview 17 + 5 = 22, selected-Lot shipment preview 17 − 5 = 12, rejection
  of fractional quantity estimates, and a one-unit shipment shortage. Public
  reads verify these previews leave stock and audit records unchanged.
- Reviewed the updated native captures. Light-theme secondary copy, warning
  badges, and success badges now measure at least 5.04:1, 5.59:1, and 5.53:1 on
  their tested surfaces. Light/dark control boundaries measure 3.41:1 and 3.49:1.
  This is targeted verification, not exhaustive accessibility certification.

### Standards review

No actionable documented-standard violations. One optional Duplicated Code /
Repeated Switches observation: activity classification is repeated for class and
icon selection. The expressions are local and consistent with existing style;
no additional abstraction was introduced solely to address this suggestion.

### Spec review

No actionable findings against this confirmed scope and the approved Phase 0
reference. Python authority, transaction confirmation, drafts, uncertainty
recovery, and the distinction between inventory health and shipment readiness
remain intact. Deferred workflows retain their existing scope.

Review totals: Standards 0 hard violations, 1 optional suggestion (activity
classification); Spec 0 findings. Independent reviewers inspected the diff;
runtime verification was performed by the implementing agent.
