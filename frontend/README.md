# InvSys desktop frontend

Vite/TypeScript assets for the pywebview desktop shell. Python `InventoryStore`
owns stock, low-stock status, and persistence; this code collects input and
displays bridge results. See [desktop.md](../docs/frontend/desktop.md) for
launch, scope, the bridge contract, and recovery behavior.

```bash
npm ci
npm run check
npm run build
```

`npm run build` checks types and then builds the assets. CI runs `npm run check`
and `npm run build:assets` as separate steps. The project requires Node 22+;
use Node 22.12+ on the 22.x line to satisfy the locked Vite release. CI uses
Node 22. No frontend test runner is installed.

`npm run dev` serves the UI, but a normal browser has no Python bridge, so it
deliberately shows an unavailable-connection state. Use the desktop launcher from
the repository root to exercise live operations.

Vite builds a classic IIFE script and CSS; `scripts/build-html.mjs` writes the
relative local HTML entry point. `dist/` contains `index.html`, `app.js`, and
`style.css`. This avoids ES-module file-origin restrictions without adding a
server or build plugin. All icons and styles are bundled locally.

## Source map

- `src/bridge.ts`: strict use-case client and response DTOs. Waits for
  `pywebviewready` and reports a timeout with a reconnect action. Never falls
  back to fixture data or retries mutations.
- `src/main.ts`: shell, dashboard, Parts catalog and drawer, dialogs, theme.
- `src/stock.ts`: Receive and standard/BOM Ship drafts, reviews, and uncertain
  submission reconciliation.
- `src/history.ts`: History search, filters, paging, and the read-only drawer.
- `src/styles.css`: design tokens and both themes.

## Presentation and navigation

Dashboard shortage arrows open Receive with the Part selected; the Low-stock
summary and View all action open filtered Parts. Receive reviews preview stock at
the selected Location, while standard Ship reviews highlight the selected Lot.
These estimates use the last availability read and never replace Python
validation or shipment confirmation. BOM reviews emphasize component
requirements and Lot allocations. Low stock stays amber, with an explicit
No stock label at zero; blocked shipment shortages and errors use red.

Part details have a contextual View History action; failed transaction or
shipment detail reads offer Retry details inside the open drawer.
See [confirmed frontend polish decisions](../docs/frontend/polish-decisions.md)
for the presentation scope and its executed native validation.
