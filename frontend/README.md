# InvSys desktop frontend

This is the live dashboard/catalog slice for issue #7, based on approved layout A.
The reference remains on `prototype/invsys-phase0`; fixture workflows are not
included here. Python InventoryStore owns stock, low-stock status, and persistence.

```bash
npm ci
npm run check
npm run build
```

Node must satisfy the locked Vite release's engine requirement (Node 20.19+ or
22.12+). Development uses `npm run dev`, but a normal browser has no Python
bridge: it deliberately shows an unavailable-connection state. Use the desktop
launcher from the repository root to exercise live operations. No frontend test
runner has been introduced.

Vite builds a classic IIFE script and CSS; `scripts/build-html.mjs` writes the
relative local HTML entry point. `dist/` contains `index.html`, `app.js`, and
`style.css`. This avoids ES-module file-origin restrictions without adding a
server or build plugin. All icons and styles are bundled locally.

`src/bridge.ts` defines the strict use-case client and response DTOs. The shell
waits for `pywebviewready`, handles an already-ready bridge, and reports a timeout
with an explicit reconnect action. Requests never fall back to fixture data.
Read failures offer Refresh/Retry; mutations are not automatically retried. An
uncertain create preserves entries and requires closing and refreshing the
catalog to reconcile against an authoritative part read before resubmission.

Search/filter/sort state stays local. Opening a native dialog does not rebuild
the catalog. Dialogs trap focus, support Escape, restore focus, and the drawer
restores table/page position. Both themes use visible keyboard focus and reduced
motion styles. Operator and explicit theme choice use existing Python settings.

See [desktop launch and validation](../docs/frontend/desktop.md).
