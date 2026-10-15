# Standalone offline bundle

`scripts/package_bundle.py` turns the built frontend and the pywebview launcher into
a self-contained, one-directory bundle that runs without Python, Node, a frontend
development server, a CDN or any inventory HTTP service. Linux (ticket #52) and
macOS (ticket #54) are delivered. The Windows ticket extends the same script, lock
file and CI job; it does not add a second build path. Full installers, Developer ID
signing, notarization, auto-update and release publication are out of scope.

What the bundle is: PyInstaller (`--onedir`) freezing `inventory_desktop.py` with
the exact `frontend/dist` assets, PySide6 with Qt WebEngine and pywebview's Qt
backend. `bundle-manifest.json` records the source commit, the
Python/PyInstaller/PySide6/pywebview/QtPy versions and the SHA-256 of every
bundled asset.

| Platform | Bundle | Executable | Manifest |
| --- | --- | --- | --- |
| Linux | `invsys-desktop/` folder | `invsys-desktop/invsys-desktop` | `invsys-desktop/bundle-manifest.json` |
| macOS | `invsys-desktop.app` application (`--windowed`, bundle identifier `io.github.theozex4ever.invsys`) | `invsys-desktop.app/Contents/MacOS/invsys-desktop` | `invsys-desktop.app/Contents/Resources/bundle-manifest.json` |

On macOS the folder PyInstaller builds the application from is removed; only the
`.app` is delivered. PyInstaller signs the application ad hoc; adding the manifest
breaks that seal, so the build re-signs it ad hoc (`codesign --force --sign -`) and
fails unless `codesign --verify --deep --strict` accepts it. An ad-hoc signature
is not a Developer ID signature: see [unsigned distribution](#unsigned-distribution-macos).

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

The commands are the same on macOS (`codesign`, part of macOS, re-seals the
application). Output: `/tmp/invsys-dist/invsys-desktop/` and an
`invsys-desktop-linux-x86_64.tar.gz` archive on Linux;
`/tmp/invsys-dist/invsys-desktop.app` and `invsys-desktop-darwin-arm64.tar.gz` on
Apple silicon. Archives have sorted entries, keep symbolic links and permissions,
neutral ownership and
no embedded timestamps; an archive is deterministic for identical bundle
contents, but the frozen binaries themselves are not claimed to be bit-reproducible).
Build with Python 3.12, the CI baseline. A macOS bundle contains the build
machine's architecture only (the CI builds arm64 on Apple silicon). The build refuses to run without the
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

## Install and run (macOS)

Prerequisites on the operator's Mac:

- macOS 13 Ventura or later: the bundled PySide6 6.11.2 (Qt 6.11) wheels are
  built for macOS 13 and newer. **Verified target:** only the GitHub-hosted
  `macos-15` runner (macOS 15, Apple silicon virtual machine) recorded
  [below](#recorded-macos-evidence). Other macOS versions are untested.
- Apple silicon (arm64). The bundle holds one architecture, the build machine's;
  an Intel Mac needs a bundle built on an Intel Mac, which is untested.
- A logged-in desktop session. Nothing else to install: the bundle carries
  Python, Qt and Qt WebEngine, and the Settings folder buttons use the built-in
  `open` command.

```bash
mkdir -p ~/Applications
tar -xzf invsys-desktop-darwin-arm64.tar.gz -C ~/Applications
~/Applications/invsys-desktop.app/Contents/MacOS/invsys-desktop --database ~/invsys-data/inventory.db
```

Launch from Terminal as above, so the readable startup failures (table below) are
visible. `open ~/Applications/invsys-desktop.app --args --database <file>` also
works but discards those messages. Opening the application from Finder or the Dock
passes no `--database`, so it exits at once without a window: by design, a bundle
never opens an inventory it was not told to open. Remove by deleting the `.app`;
upgrade by replacing it. Nothing is written inside the application; inventory data,
backups, exports and logs live beside the selected database.

Choose a database folder such as `~/invsys-data`. Desktop, Documents, Downloads,
iCloud Drive and removable or network volumes are privacy-protected: macOS asks
whether Terminal (or the application) may access them, and a refusal ends the
launch with "Cannot open the inventory database ... Operation not permitted".

### Unsigned distribution (macOS)

The application carries only an ad-hoc signature: no Developer ID, no
notarization. Its seal is intact (the build and the smoke check it), but Gatekeeper
does not trust it: the package smoke records `spctl --assess` rejecting the
application. What that means for operators:

- A copy that arrived through a browser, mail, AirDrop or a messaging app is
  quarantined, and macOS refuses its first launch ("Apple could not verify ...").
  Approve it once: after the refused launch, open System Settings > Privacy &
  Security, choose **Open Anyway** for `invsys-desktop` and confirm (macOS 15 no
  longer offers the Control-click > Open shortcut). Alternatively, after checking
  the archive's SHA-256 against the build record, clear the quarantine flag of
  this application only:
  `xattr -dr com.apple.quarantine ~/Applications/invsys-desktop.app`.
- Archives copied by `scp`, `rsync` or a USB drive, and local builds, are not
  quarantined and launch directly.
- Do not modify or re-sign files inside the application. A broken seal makes macOS
  report the application as damaged, with no **Open Anyway** option.
- A quarantined application started from Finder without being moved may run from
  a randomized read-only location (App Translocation). Nothing is written inside
  the bundle, so this does not affect data, which always follows `--database`.

None of these Gatekeeper prompts were exercised: the CI bundle is never
quarantined, and no Developer ID signature, notarized build or installer exists.

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

The messages and exit statuses are the same on Linux and macOS.

## Package smoke

```bash
xvfb-run -a -s "-screen 0 1920x1080x24" \
  python scripts/package_bundle.py smoke --bundle /tmp/invsys-dist/invsys-desktop \
  --assets frontend/dist --workdir /tmp/invsys-package-smoke \
  --evidence /tmp/invsys-package-evidence.json --isolate-network
```

(On a desktop session omit `xvfb-run`; the smoke opens real windows.) On macOS,
from a logged-in session:

```bash
python scripts/package_bundle.py smoke --bundle /tmp/invsys-dist/invsys-desktop.app \
  --assets frontend/dist --workdir /tmp/invsys-package-smoke \
  --evidence /tmp/invsys-package-evidence.json
```

The workdir
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
5. with `--isolate-network` (Linux only), runs everything inside an empty network
   namespace (`unshare --net`, no interface at all) so any network use fails;
6. on macOS, after both runs, requires `codesign --verify --deep --strict` to
   accept the application (which also shows nothing was written inside it) and
   records its signature details and Gatekeeper's verdict.

macOS differences, stated plainly:

- **Offline:** macOS has no unprivileged network namespace, so `--isolate-network`
  stops with a readable error there. Offline operation on macOS rests on the same
  in-process checks as everywhere (assets load over `file://`, the smoke fails if
  pywebview starts an HTTP server) and on `npm run check:dist`, which rejects
  built assets containing network URLs. Network use by the
  bundle itself is not ruled out by isolation on macOS.
- **Import dialogs:** NSOpenPanel, the Cocoa panel Qt shows for file selection,
  cannot be operated by another program. On macOS the smoke therefore switches Qt
  to its own file dialog (`AA_DontUseNativeDialogs`, smoke runs only) before it
  drives the three CSV imports. The bridge, pywebview and Qt selection path is the
  one operators use; the Cocoa panel itself is exercised only by an operator.

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

The `package-smoke` job (matrix over runners: `ubuntu-24.04` and `macos-15`)
runs after the `frontend` job: it installs the package lock, downloads the exact
`frontend-dist` artifact the other jobs tested, builds the bundle, checks the
checkout stayed clean and runs the package smoke: under Xvfb in an empty network
namespace on Linux, in the runner's logged-in session on macOS. It uploads
`package-evidence.json`, the manifest, captures and logs for 14 days. Archives are
not uploaded (about 260 MB each). Both legs are part of **CI gate**.

## Extending to Windows

Extend, do not fork: add the runner to the matrix with its `bundle` name and its
display/runtime steps; adapt `bundle_path`, `executable_path`, `manifest_path`,
`pyinstaller_args` and, if needed, `make_archive` (zip) in
`scripts/package_bundle.py`; keep `requirements-package.txt` as the single
bundling dependency list, with platform markers if a tool is OS-specific. The
launcher contract (explicit `--database`, `--smoke-check`) is unchanged.

## Limitations and evidence

See the recorded Linux and macOS runs below. Not established by these tickets:
Windows bundles, Linux distributions and macOS versions other than the recorded
ones, Intel Macs, the glibc compatibility matrix, Gatekeeper approval of a
quarantined download, performance targets (P05 packaged launch time), human
operator acceptance, Developer ID signing, notarization, installers, auto-update
and release publication.

## Recorded Linux evidence

Recorded 2026-10-15 (UTC timestamps in the record) by `scripts/package_bundle.py`
on the reference machine below, from a clean checkout of commit `a94cdfe`
(`uncommitted_changes: false` in the manifest). The run used a real desktop
session, **not** Xvfb. The CI job (Ubuntu 24.04 under Xvfb) is the repeatable
evidence; its result and uploaded evidence are on the pull request checks.

| Item | Value |
| --- | --- |
| Reference machine | AMD Ryzen 5 1600 (12 logical CPUs), 32 GB RAM, CachyOS, Linux 7.2.9-2-cachyos x86-64, glibc 2.44, Wayland session |
| Toolchain | Python 3.12.13, PyInstaller 6.22.3, pyinstaller-hooks-contrib 2026.8, PySide6 6.11.2, pywebview 6.2.1, QtPy 2.4.3 (from `requirements-package.lock.txt`) |
| Bundle | 3,017 files, 686,878,052 bytes; `invsys-desktop` SHA-256 `a8a1f90e…eea52fc9` |
| Archive | `invsys-desktop-linux-x86_64.tar.gz`, 270,472,314 bytes, SHA-256 `9591c37b…d8bf1f`; the smoke ran on the archive extracted into a fresh directory |
| Assets | `index.html`, `app.js`, `style.css` byte-identical to `frontend/dist` (SHA-256 per file in the manifest) |
| Failure checks | no database, missing bundled assets, database folder that is a file, database path that is a directory, non-SQLite file: all exit as documented with readable messages, no traceback, no inventory created |
| Native smoke, run 1 and 2 | both exit 0 (about 61 s each, dominated by the probe's own waits; this is **not** the P05 launch-time measurement); run 1 took no startup backup; run 2 took one holding exactly run 1's 39 ledger rows |
| Persistence | SQLite integrity `ok`; all 39 ledger rows of run 1 present after run 2 (76 total), parts 13 → 22, shipments 5 → 10; nothing written to `INVSYS_HOME` |
| Offline | run inside an empty network namespace (`--isolate-network`) with no HTTP server (the smoke fails if pywebview starts one); native reduced-motion check passed (`QTWEBENGINE_CHROMIUM_FLAGS=--force-prefers-reduced-motion`) |

[`evidence/linux-package-2026-10-15.json`](evidence/linux-package-2026-10-15.json)
holds the full record. During development, earlier builds of this ticket's tree
passed the same checks three times (build output with and without network
isolation, and an extracted archive); only this final run on the committed tree is
retained. Two builds of the same commit are not byte-identical (frozen binaries
embed build metadata); the guarantee is the exact-asset check, not bundle
reproducibility.

Not exercised: the Xvfb path and the CI job locally (no Xvfb on the reference
machine), distributions other than CachyOS, X11-only sessions, the file-manager
launch (`xdg-open`) beyond the smoke's recording host, performance targets, and
operator acceptance.
