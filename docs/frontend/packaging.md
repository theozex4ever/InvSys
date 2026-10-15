# Standalone offline bundle

`scripts/package_bundle.py` turns the built frontend and the pywebview launcher into
a self-contained, one-directory bundle that runs without Python, Node, a frontend
development server, a CDN or any inventory HTTP service. Linux is delivered
(ticket #52). The Windows and macOS tickets extend the same script, lock file and CI
job; they do not add a second build path. Full installers, signing, auto-update and
release publication are out of scope.

What the bundle is: PyInstaller (`--onedir`) freezing `inventory_desktop.py` with
the exact `frontend/dist` assets, PySide6 with Qt WebEngine and pywebview's Qt
backend. `bundle-manifest.json` beside the executable records the source commit,
the Python/PyInstaller/PySide6/pywebview/QtPy versions and the SHA-256 of every
bundled asset.

## Build

Use a hash-locked environment separate from the test environment. The package lock
is constrained to `requirements.lock.txt`, so the bundle contains the runtime
versions the tests ran against.

```bash
python -m venv /tmp/invsys-build && . /tmp/invsys-build/bin/activate
python -m pip install --require-hashes -r requirements-package.lock.txt
npm ci --ignore-scripts --prefix frontend
npm run build:assets --prefix frontend && npm run check:dist --prefix frontend
python scripts/package_bundle.py build --assets frontend/dist --dist /tmp/invsys-dist --work /tmp/invsys-work
```

Output: `/tmp/invsys-dist/invsys-desktop/` and a
`invsys-desktop-linux-x86_64.tar.gz` archive (sorted entries, neutral ownership,
no embedded timestamps; the archive is deterministic for identical bundle
contents, but the frozen binaries themselves are not claimed to be bit-reproducible).
Build with Python 3.12, the CI baseline. The build refuses to run without the
built assets, verifies the bundled assets byte-for-byte against `frontend/dist`
after freezing, and keeps the `.spec` file and scratch files in `--work`, outside
the checkout. Choose `--dist` and `--work` outside the repository; the default
`dist/` and `build/` are git-ignored.

Changing the packaging dependency set: edit `requirements-package.txt`, run
`scripts/lock.sh` (needs uv) and commit `requirements-package.lock.txt`. CI fails
if the lock is stale and audits it with the other locks.

## Install and run (Linux)

Prerequisites on the operator's workstation:

- x86-64 Linux and a working X11 or Wayland session; the launcher is not an
  offscreen browser. **Verified targets:** Ubuntu 24.04 (the CI job, under Xvfb)
  and the CachyOS reference machine below. Other distributions are untested. The
  bundle links the build machine's glibc, so a bundle must be built on a machine
  no newer than the oldest distribution it should run on; the recorded local
  bundle was built on glibc 2.44 and is not claimed to run on older systems, while
  the CI bundle is built on Ubuntu 24.04 (glibc 2.39).
- The system libraries Qt WebEngine does not bundle. On Ubuntu 24.04 the CI job
  installs exactly: `libegl1 libopengl0 libxkbcommon0 libxkbcommon-x11-0
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libnss3
  libxcomposite1 libxdamage1 libxrandr2 libxtst6 libasound2t64` (the
  `QT_APT_PACKAGES` list in [`ci.yml`](../../.github/workflows/ci.yml), which
  stays authoritative), plus `xvfb xauth` only for headless runs. Other
  distributions need the equivalents.
- `xdg-open` for the Settings folder buttons.
- Chromium's sandbox needs unprivileged user namespaces. Distributions that block
  them by default (Ubuntu 24.04) need the restriction lifted, as the CI job does
  with `kernel.apparmor_restrict_unprivileged_userns=0`. The launcher never passes
  `--no-sandbox`, but pywebview 6.2.1 itself appends it on Arch, Manjaro, NixOS,
  RHEL and Pop!_OS (by `os-release` ID), so the sandbox is off there.

```bash
tar -xzf invsys-desktop-linux-x86_64.tar.gz -C ~/Applications   # any writable folder
~/Applications/invsys-desktop/invsys-desktop --database ~/invsys-data/inventory.db
```

Install by extracting; remove by deleting the directory. Nothing is written inside
the bundle. Upgrading replaces the directory only; inventory data, backups, exports
and logs live beside the selected database, never in the bundle.

## Data selection

Packaged launch **requires** `--database`, so a bundle can never silently open an
inventory inside its own directory or a temporary extraction folder. Select the
existing operational file explicitly. Backups (`backups/`), CSV exports (`exports/`)
and `logs/desktop.log` are kept beside that file, and a startup backup is taken
before the store opens. Source launches keep their defaults (`data/inventory.db`,
`INVSYS_HOME`). Nothing in the bundle opens a socket: the assets load over
`file://` and the smoke fails if pywebview starts an HTTP server.

Readable failures (exit status, no traceback, nothing written to a failed
location):

| Situation | Result |
| --- | --- |
| no `--database` | exit 2, "Packaged launch requires --database ..." |
| bundled assets missing | exit 2, "This bundle is incomplete ... Extract the bundle again" |
| database folder unusable (smoke-tested: a file where the folder belongs; also unwritable or full) | exit 1, "Cannot open the inventory database <path>: <reason>" |
| file that is not SQLite, or a directory (both smoke-tested) | exit 1, same message with the reason |

## Package smoke

```bash
xvfb-run -a -s "-screen 0 1920x1080x24" \
  python scripts/package_bundle.py smoke --bundle /tmp/invsys-dist/invsys-desktop \
  --assets frontend/dist --workdir /tmp/invsys-package-smoke \
  --evidence /tmp/invsys-package-evidence.json --isolate-network
```

(On a desktop session omit `xvfb-run`; the smoke opens real windows.) The workdir
must be empty and disposable; the smoke writes a real inventory there and never
touches operational data. It:

1. verifies the bundled assets are byte-identical to `frontend/dist`;
2. launches the bundle with no database, with its assets removed (from a hard-linked
   copy), with a database folder that is a file, a directory as the database and a
   non-SQLite file, expecting the readable failures above and no inventory created;
3. runs the bundle's native `--smoke-check` **twice** against one inventory:
   every delivered workflow (receive, ship, BOM, move, adjust, History, Settings
   backup/folder, five CSV exports, CSV imports, themes, keyboard/layout) and the
   in-process restart-persistence check; the first run must take no startup backup,
   the second must create a `*-startup.db` backup holding exactly the ledger rows
   run 1 left;
4. reads the inventory independently (SQLite integrity check, and every ledger row
   run 1 wrote must still exist after run 2) and checks that nothing was written to
   `INVSYS_HOME`, the default data location, which the smoke points at an
   unused directory;
5. with `--isolate-network`, runs everything inside an empty network namespace
   (`unshare --net`, no interface at all) so any network use fails.

It exits non-zero on any failure and writes a JSON evidence record: reference
machine (OS, kernel, glibc, CPU, memory, session), bundle size, file count,
executable hash, manifest (versions, source commit, asset hashes), each failure
check with the actual message, and each run's exit status, duration, output and
database counts.

New migrated workflows extend the existing native smoke
(`inventory_control/desktop_smoke*.py`); the bundle runs that same probe, so
package acceptance grows with it without changing this tool. Full capability
parity acceptance is ticket 18 and is not claimed here.

## CI

The `package-smoke` job (matrix over runners; Ubuntu 24.04 today) runs after the
`frontend` job: it installs the package lock, downloads the exact `frontend-dist`
artifact the other jobs tested, builds the bundle, checks the checkout stayed
clean, runs the package smoke under Xvfb in an empty network namespace, and
uploads `package-evidence.json`, the manifest, captures and logs for 14 days. The
archive is not uploaded (about 260 MB). The job is part of **CI gate**.

## Extending to Windows and macOS

Extend, do not fork: add the runner to the matrix and its display/runtime steps;
adapt `pyinstaller_args`, `executable_path` and `make_archive` (zip, `.app`) in
`scripts/package_bundle.py`; keep `requirements-package.txt` as the single
bundling dependency list, with platform markers if a tool is OS-specific. The
launcher contract (explicit `--database`, `--smoke-check`) is unchanged.

## Limitations and evidence

See the recorded Linux run below. Not established by this ticket: Windows/macOS
bundles, distributions other than the recorded ones, glibc compatibility matrix,
performance targets (P05 packaged launch time), human operator acceptance, signed
installers, auto-update and release publication.

## Recorded Linux evidence

Recorded 2026-10-14 by `scripts/package_bundle.py` on the reference machine below.
These runs used a real desktop session, **not** Xvfb, and were made from a working
tree with the changes of this ticket not yet committed (the manifest records base
commit `d378088` with `uncommitted_changes: true`). The CI job (Ubuntu 24.04 under
Xvfb) is the repeatable evidence; its result and uploaded evidence are on the pull
request checks.

| Item | Value |
| --- | --- |
| Reference machine | AMD Ryzen 5 1600 (12 logical CPUs), 32 GB RAM, CachyOS, Linux 7.2.9-2-cachyos x86-64, glibc 2.44, Wayland session |
| Toolchain | Python 3.12.13, PyInstaller 6.22.3, pyinstaller-hooks-contrib 2026.8, PySide6 6.11.2, pywebview 6.2.1, QtPy 2.4.3 (from `requirements-package.lock.txt`) |
| Bundle | 3,017 files, 686,878,043 bytes; `invsys-desktop` SHA-256 `e93e0a12…2fba3182` |
| Archive | `invsys-desktop-linux-x86_64.tar.gz`, 270,472,514 bytes, SHA-256 `6dba68fd…a8cd8378` |
| Assets | `index.html`, `app.js`, `style.css` byte-identical to `frontend/dist` (SHA-256 per file in the manifest) |
| Failure checks | no database, missing bundled assets, database folder that is a file, non-SQLite file: all exit as documented with readable messages, no traceback, no inventory created |
| Native smoke, run 1 and 2 | both exit 0 (about 61 s each, dominated by the probe's own waits; this is **not** the P05 launch-time measurement); run 2 wrote an `inventory-*-startup.db` backup |
| Persistence | SQLite integrity `ok`; transactions 39 → 76, parts 13 → 22, shipments 5 → 10 across the restart; nothing written to `INVSYS_HOME` |
| Offline | the same runs inside an empty network namespace (`--isolate-network`) and no HTTP server (the smoke fails if pywebview starts one); native reduced-motion check passed |

Three complete runs were made, each with its own disposable inventory: the build
output without network isolation, the build output with `--isolate-network` and
`QTWEBENGINE_CHROMIUM_FLAGS=--force-prefers-reduced-motion`, and the archive
extracted into a fresh directory with the same flags. All three passed. The
record of the last (installed-archive) run is kept in
[`evidence/linux-package-2026-10-14.json`](evidence/linux-package-2026-10-14.json);
the CI job uploads its own on every run.

Not exercised: the Xvfb path and the CI job locally (no Xvfb on the reference
machine), distributions other than CachyOS, X11-only sessions, the file-manager
launch (`xdg-open`) beyond the smoke's recording host, performance targets, and
operator acceptance.
