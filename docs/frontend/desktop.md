# Live desktop dashboard and catalog

Issue [#7](https://github.com/theozex4ever/InvSys/issues/7) implements the first
slice of [#6](https://github.com/theozex4ever/InvSys/issues/6), using
[approved layout A](phase0-design.md). This is not the full frontend migration.

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
the prototype's npm lockfile (Vite, strict TypeScript, lucide; no framework).

Normal source launch uses the existing `data/inventory.db`, `backups/`, and
`logs/` paths. Startup backs up an existing database before opening InventoryStore,
with the existing retention policy. The original `python inventory_visualizer.py`
launcher remains available for all inventory operations.

Review with an explicit disposable database:

```bash
python inventory_desktop.py --database /tmp/invsys-review/inventory.db
python inventory_desktop.py --database /tmp/invsys-smoke/inventory.db --smoke-check
```

An explicit database keeps backups and `logs/desktop.log` beside that database.
Importing the bridge does not initialize the original application's shared store.
The smoke command saves operator `Desktop smoke`, creates `DESKTOP-SMOKE` if
absent, inspects its drawer, exits, and verifies persistence through a reopened
store. Use a disposable file: these are real writes. Repeat the command to check
startup backups and restart reads. No seed inventory is inserted by the launcher.

Built assets load directly over `file://` with `http_server=False`. An explicit
file URI avoids pywebview automatically starting a server for a bare local path
([pywebview usage](https://pywebview.flowrl.com/guide/usage.html)). The build uses
relative local assets ([Vite build documentation](https://vite.dev/guide/build.html)).
There is no Vite process, HTTP server, CDN, or network inventory service required.

## Basic package proof

Full installers and release packaging remain deferred. A Linux one-directory
PyInstaller proof includes the built frontend:

```bash
pip install pyinstaller
pyinstaller --noconfirm --name invsys-desktop --onedir \
  --add-data frontend/dist:frontend/dist \
  --hidden-import webview.platforms.qt \
  --hidden-import PySide6.QtWebEngineWidgets \
  --hidden-import PySide6.QtWebEngineCore \
  --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 \
  --exclude-module tkinter --exclude-module gi inventory_desktop.py
./dist/invsys-desktop/invsys-desktop --database /tmp/invsys-packaged/inventory.db --smoke-check
```

Packaged launch requires `--database` explicitly, so it cannot silently open an
inventory file inside a bundle or temporary extraction directory. Select the
existing operational file explicitly when appropriate. `--assets` overrides the
built asset directory for local review; it is not needed for bundled assets.
This package is a platform-specific smoke artifact, not a distributable release.

## Scope and contract

Available: live dashboard counts/low-stock/activity, header operator save,
remembered light/dark choice, catalog search/filter/sort, part creation, and
read-only drawer with fields and lot/location balances. Low-stock entries open
live parts; the attention panel shows five entries and links to all low-stock
parts. Active and low-stock indicators are separate. The frontend never computes
stock or invents catalog fields.

Receive/Ship, Move/Adjust, BOM tooling, History inspection, part editing and
activation, location administration, and operational Settings are deferred and
identified in the shell/drawer. Dashboard activity has no pretend History links.
Continue those workflows in the original application.

The bridge exposes only dashboard, preferences, save operator/theme, locations,
part search/detail/create. It validates input shapes/types before using the store
and returns `{ok: true, data}` or `{ok: false, error: {code, message}}`. Stable
codes: `VALIDATION`, `DUPLICATE`, `NOT_FOUND`, `INTERNAL`. Unexpected exceptions
are logged and return a safe message. Private helpers, store/session access,
SQL, arbitrary settings, and stock updates are not exposed. Requests from this
window are serialized; cross-process transactional behavior remains the store's
existing behavior. No schema or inventory rules changed.

## Validation record (2026-10-01)

Automated integration checks use the agreed public bridge boundary against real
temporary SQLite files. They cover dashboard/empty reads, setting persistence,
search/filter/sort, per-lot/location balances, creation/restart, invalid requests,
unknown records, separate active/low-stock state, and safe logged exceptions.

Native smoke checks exercise real pywebview/Qt WebEngine, built local assets,
operator save, part creation, live drawer, theme save, and restart persistence.
A broader native keyboard/viewport check uses disposable real catalog/lot data:
light/dark at 1366 × 768, 1920 × 1080, and 800 × 650; no horizontal page overflow;
Tab/Shift+Tab inside both dialogs; Escape and focus restoration; low-stock detail
navigation; duplicate feedback retaining input; search and page position retained
when a drawer closes. These checks exposed and led to explicit dialog focus
trapping and scroll restoration.

Exact final gate and package results are recorded below when run. Reduced-motion
CSS is implemented; OS-level reduced-motion emulation, Windows/macOS packaging,
and human operator usability acceptance remain follow-up checks. Do not treat the
native probe as exhaustive accessibility or release validation.

Final executed results:

- `QT_QPA_PLATFORM=offscreen pytest`: **215 passed** (6.40 s).
- `npm run check --prefix frontend`: strict TypeScript passed.
- `npm run build --prefix frontend`: passed; HTML, IIFE JS and CSS emitted.
- Ruff lint and format checks on new Python modules/tests: passed.
- Native source launcher `--smoke-check`: passed against a disposable database.
- Linux PyInstaller one-directory build: passed. Refreshed the bundle's frontend
  files after the final UI fixes; packaged `--smoke-check` passed with local assets,
  no HTTP server, operator/create/drawer behavior, and reopened-database reads.
- Broader native Qt keyboard/viewport smoke: passed after the focus and scroll
  fixes described above. Viewport captures were visually inspected.
- Native recovery smoke: passed. A real create committed before an injected lost
  transport response; repeated submit was suppressed, entries stayed intact,
  reconciliation used the submitted number despite later edits, and a delayed
  reconciliation could not replace results for a newer search.
- Native readiness smoke without a use-case bridge: passed; readable unavailable
  state, disabled mutations, and reconnect action. Packaged restart also produced
  a startup backup containing the saved operator.
- Two-axis code review: Standards **0 remaining findings**, Spec **0 remaining
  findings** after fixing uncertain-create identity and stale read handling.
