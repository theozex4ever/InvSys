# Standalone offline bundle

`scripts/package_bundle.py` turns the built frontend and the pywebview launcher into
a self-contained, one-directory bundle that runs without Python, Node, a frontend
development server, a CDN or any inventory HTTP service. Linux (ticket #52),
Windows (ticket #53) and macOS (ticket #54) have retained automated package
evidence. Native Cocoa-panel and Finder acceptance on macOS remains pending as
recorded [below](#recorded-macos-evidence). All three platforms share the same
script, lock file and CI job. Full installers, Developer ID signing, notarization,
auto-update and release publication are out of scope.

What the bundle is: PyInstaller (`--onedir`) freezing `inventory_desktop.py` with
the exact `frontend/dist` assets, PySide6 with Qt WebEngine and pywebview's Qt
backend. `bundle-manifest.json` records the source commit, the
Python/PyInstaller/PySide6/pywebview/QtPy versions and the SHA-256 of every
bundled asset.

| Platform | Bundle | Executable | Manifest |
| --- | --- | --- | --- |
| Windows | `invsys-desktop/` folder | `invsys-desktop/invsys-desktop.exe` | `invsys-desktop/bundle-manifest.json` |
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

On Windows (PowerShell, Python 3.12 x64 and Node 22 on `PATH`) the steps are the same:

```powershell
py -3.12 -m venv $env:TEMP\invsys-build; & $env:TEMP\invsys-build\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements-package.lock.txt
npm ci --ignore-scripts --prefix frontend
npm run build:assets --prefix frontend; npm run check:dist --prefix frontend
python scripts/package_bundle.py build --assets frontend/dist --dist $env:TEMP\invsys-dist --work $env:TEMP\invsys-work
```

Output: `invsys-desktop\invsys-desktop.exe` and a `invsys-desktop-win32-amd64.zip`
archive (sorted entries, a fixed 1980-01-01 timestamp and fixed attributes, so it is
deterministic for identical bundle contents). The one lock file covers Windows
through platform markers; nothing Windows-only is added to it. The Windows freeze
differs from the shared one only by `--noupx` (UPX-packed executables trip antivirus
heuristics) and by excluding pywebview's .NET backends (`clr`, `clr_loader`,
`pythonnet`): the bundle uses the Qt backend only, so no .NET runtime or Microsoft
Edge WebView2 is needed. The executable is a console program on purpose (see
[readable failures](#data-selection)).

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

## Install and run (Windows)

Prerequisites on the operator's workstation:

- 64-bit Windows 10 or 11 (Qt 6's supported Windows versions) and a normal desktop
  session. **Verified target:** the GitHub `windows-2025` runner (Windows Server 2025
  Datacenter, build 26100), see the evidence below. Windows 10/11 desktop editions
  have not been run.
- Nothing else: the bundle carries Python, Qt and Qt WebEngine with the runtime
  libraries they ship. Qt WebEngine falls back to software rendering without a GPU (the CI
  runner has none). No .NET runtime, WebView2, Node or Python install is needed.
- Explorer for the Settings folder buttons (opened with the shell's default handler).
  CSV imports use the standard Windows file dialog.

Install by extracting the zip (Explorer's "Extract All…" or PowerShell) into a folder
the operator can write, for example `%LOCALAPPDATA%\Programs`. Keep the whole
`invsys-desktop` folder together: `invsys-desktop.exe` needs its `_internal` folder.

```powershell
Expand-Archive invsys-desktop-win32-amd64.zip -DestinationPath $env:LOCALAPPDATA\Programs
& "$env:LOCALAPPDATA\Programs\invsys-desktop\invsys-desktop.exe" --database "$env:USERPROFILE\invsys-data\inventory.db"
```

For everyday use, create a shortcut whose target is the executable followed by
`--database "<path to inventory.db>"`. The bundle is a console program, so a console
window opens next to the application and closes with it. When a launch fails, the
reason is printed there and, if the bundle was started from Explorer or a shortcut,
the window stays open with "Press Enter to close this window." Started from an open
PowerShell or Command Prompt, the message is printed there and the bundle exits
at once. Remove by deleting the folder (and the shortcut); upgrading replaces the
folder only. The bundle is not signed: SmartScreen or antivirus software may ask
before the first launch.

## Install and run (macOS)

Prerequisites on the operator's Mac:

- macOS 13 Ventura or later: the bundled PySide6 6.11.2 (Qt 6.11) wheels are
  built for macOS 13 and newer. **Verified automated target:** the GitHub-hosted
  `macos-15` runner (macOS 15.7.9, Apple silicon virtual machine); see
  [the retained run](#recorded-macos-evidence). macOS 13/14 and Intel Macs have
  not been tested.
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
does not trust it: the package smoke records the actual `spctl --assess`
verdict rather than treating an ad-hoc signature as distribution approval.
What that means for operators:

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

On Windows a launch from Explorer or a shortcut waits for Enter after any of these
failures, and after an unexpected error (its traceback is printed first).

| Situation | Result |
| --- | --- |
| no `--database` | exit 2, "Packaged launch requires --database ..." |
| bundled assets missing | exit 2, "This bundle is incomplete ... Extract the bundle again" |
| database folder unusable (smoke-tested: a file where the folder belongs; also unwritable or full) | exit 1, "Cannot open the inventory database <path>: <reason>" |
| file that is not SQLite, or a directory (both smoke-tested) | exit 1, same message with the reason |
| Windows: a drive letter nothing is mapped to (smoke-tested on Windows) | exit 1, same message with the reason |

These messages and exit statuses passed the applicable Linux, Windows and macOS package smokes
recorded below.

## Package smoke

```bash
xvfb-run -a -s "-screen 0 1920x1080x24" \
  python scripts/package_bundle.py smoke --bundle /tmp/invsys-dist/invsys-desktop \
  --assets frontend/dist --workdir /tmp/invsys-package-smoke \
  --evidence /tmp/invsys-package-evidence.json --isolate-network
```

(On a desktop session omit `xvfb-run`; the smoke opens real windows.) On Windows, from
an elevated PowerShell (the firewall rules need administrator rights; without
`--isolate-network` a normal prompt is enough), smoke the *extracted archive*:

```powershell
Expand-Archive $env:TEMP\invsys-dist\invsys-desktop-win32-amd64.zip -DestinationPath $env:TEMP\invsys-installed
python scripts/package_bundle.py smoke --bundle $env:TEMP\invsys-installed\invsys-desktop `
  --assets frontend/dist --workdir $env:TEMP\invsys-package-smoke `
  --evidence $env:TEMP\invsys-package-evidence.json --isolate-network
```

On macOS, from a logged-in session:

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
5. with `--isolate-network`, makes any network use fail: on Linux every launch runs
   in an empty network namespace (`unshare --net`, no interface at all); on Windows
   the smoke first requires every Windows Firewall profile to be on, then adds an
   outbound block rule for every `.exe` in the bundle (the launcher and
   `QtWebEngineProcess.exe`), checks Windows lists them all, and deletes them when
   the smoke ends, also on failure. Windows never filters loopback, so a local HTTP
   server is caught by the launcher's "no HTTP server" check on both systems.
6. on macOS, after both runs, requires `codesign --verify --deep --strict` to
   accept the application (which also shows nothing was written inside it) and
   records its signature details and Gatekeeper's verdict.

On Windows the import step of the native smoke selects its CSV files through the real
Windows file dialog (typing the path and pressing Open or Cancel). Both Settings
folder buttons call the real system opener (`os.startfile`); the probe then reads
Explorer's displayed folder through `Shell.Application.Windows`, requires a new
visible window at the exact selected-inventory backup/export path, and closes only
that new window. Each run records the actual path, location URL, window handle,
visibility and cleanup in `smoke-captures/windows-folders.json`; the package JSON
retains both runs separately and fails without verified observations for both
folders. A Windows regression also checks that a no-op system opener fails this
observer. Explorer verification has a 40-second end-to-end smoke budget (initial
snapshot, opener, navigation and cleanup), with five seconds reserved for cleanup;
each PowerShell snapshot is capped by the remaining observation budget. Only the
three Windows folder-click UI waits allow 45 seconds for that probe and the bridge
response. General workflow waits and approved performance thresholds are unchanged.
Linux/macOS keep their recording folder host. The Windows smoke also
launches against a drive letter nothing is mapped to. It needs
English `netsh` output to read the firewall profile states and refuses to run
isolated otherwise.

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

The `package-smoke` job (runners `ubuntu-24.04`, `windows-2025` and `macos-15`)
runs after the `frontend` job: it installs the package lock, downloads the exact
`frontend-dist` artifact the other jobs tested, builds and extracts the archive
into a fresh installation directory, checks the checkout stayed clean and runs the
extracted package smoke twice. Linux uses Xvfb in an empty network namespace;
Windows uses the runner's interactive desktop behind outbound firewall rules;
macOS uses the runner's logged-in session and verifies the application seal.
It uploads `package-evidence.json`, the manifest, build/smoke output, captures,
application logs and archive checksums for 90 days, including failed-step output.
A passing macOS job also uploads the intact archive and `SHA256SUMS` as
`macos-standalone-bundle` for seven days so native-panel acceptance can use the
exact tested bundle. This is a CI artifact, not a release publication. Linux and
Windows archives are not uploaded. The same job then runs `scripts/package_perf.py` on the extracted bundle against a freshly built large inventory and uploads `perf-evidence.json` (see [performance.md](performance.md)). All three legs are part of **CI gate**.

## Extending packaging

Extend, do not fork: add a runner to the matrix with its `bundle` name and its
display/runtime steps; adapt `bundle_path`, `executable_path`, `manifest_path`,
`pyinstaller_args`, `archive_name`, `make_archive` and `network_isolation` in
`scripts/package_bundle.py`; keep `requirements-package.txt` as the single
bundling dependency list, with platform markers if a tool is OS-specific. The
launcher contract (explicit `--database`, `--smoke-check`) is unchanged.

## Limitations and evidence

See the recorded Linux, Windows and macOS runs and pending manual acceptance below. Not established
by these tickets:
Windows 10/11 desktop editions, Linux distributions and macOS versions other than the recorded
ones, Intel Macs, the glibc compatibility matrix, Gatekeeper approval of a
quarantined download, performance on designated workstations (measured on the hosted runners and one local Linux machine: [performance.md](performance.md)), human
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

## Recorded Windows evidence

### Historical run — 2026-10-19

Recorded 2026-10-19 (UTC) by the `package-smoke` CI job, [run
39190637774](https://github.com/theozex4ever/InvSys/actions/runs/39190637774)
attempt 1, from a clean checkout of commit `827bf0a` (`uncommitted_changes: false`).
No physical Windows reference machine was available; the GitHub-hosted runner below
is the reference machine.

| Item | Value |
| --- | --- |
| Reference machine | GitHub `windows-2025` runner: Windows Server 2025 Datacenter 10.0.26100, AMD EPYC 7763 (4 logical CPUs), 16 GB RAM, no GPU, interactive desktop session |
| Toolchain | Python 3.12.10, PyInstaller 6.22.3, pyinstaller-hooks-contrib 2026.8, PySide6 6.11.2, pywebview 6.2.1, QtPy 2.4.3 (from `requirements-package.lock.txt`) |
| Bundle | 3,026 files, 593,940,677 bytes; `invsys-desktop.exe` SHA-256 `03ad3e0f…a3e9fa82` |
| Archive | `invsys-desktop-win32-amd64.zip`, 226,534,236 bytes, SHA-256 `910cbe04…dac19676`; the smoke ran on the archive extracted with `Expand-Archive` |
| Assets | `index.html`, `app.js`, `style.css` byte-identical to `frontend/dist` |
| Failure checks | no database, missing bundled assets, database folder that is a file, database path that is a directory, non-SQLite file, unmapped drive letter: all exit as documented with readable messages, no traceback, no inventory created |
| Native smoke, run 1 and 2 | both exit 0 (about 99 s and 106 s); run 1 took no startup backup; run 2 took one holding exactly run 1's 42 ledger rows |
| Persistence | SQLite integrity `ok`; all 42 ledger rows of run 1 present after run 2 (82 total), parts 18 → 32, shipments 6 → 12; nothing written to `INVSYS_HOME` |
| Offline | all three firewall profiles on; outbound blocked for `invsys-desktop.exe` and `QtWebEngineProcess.exe`; no HTTP server; native reduced-motion check passed |

[`evidence/windows-package-2026-10-19.json`](evidence/windows-package-2026-10-19.json)
holds the full record. Earlier runs of this ticket's tree failed the second native
run intermittently: a confirmation dialog's queued `close` event arrived after the
next review had reopened it and discarded that review, so Confirm did nothing. The
smoke's event trace showed it, and Ship, Move and Adjust now ignore a close event
that arrives while their dialog is open again (History already did). Attempt 2 of the same run (a
re-run of the Windows job) passed as well. Qt WebEngine
logs harmless `SharedImageManager::ProduceMemory` errors on stderr with software
rendering.

Not exercised: Windows 10/11 desktop editions, a physical machine or GPU, non-English
Windows, Explorer launches by double-click (the Enter prompt is covered by unit
tests only), the Settings folder buttons' `os.startfile`, performance targets, and
operator acceptance. These limitations describe this historical run; the current
Windows probe now requires real visible Explorer navigation for both folder buttons.

### Integrated candidate 2026-10-22

All 19 checks passed on PR #78 head
`c6af0677b41c697f09d972f18fb2af852539394f`: [CI run
39777209762](https://github.com/theozex4ever/InvSys/actions/runs/39777209762)
and [CodeQL run
39777209760](https://github.com/theozex4ever/InvSys/actions/runs/39777209760).
The bundle manifest identifies the clean GitHub integration merge
`9adfd617f4fe15ddeb909a62a99e974c10d4370e`, combining that head with base
`e33afb1949b82491fa62883488079031a59ba6c2`. The integration merge and PR head
have identical trees; the manifest source is the merge SHA, not the head SHA.

The unmodified [full JSON record](evidence/windows-package-2026-10-22.json)
retains each run's Explorer observations, actual startup errors, assets, machine,
toolchain and persistence results. The original [archive checksum
record](evidence/windows-package-2026-10-22.SHA256SUMS) identifies
`invsys-desktop-win32-amd64.zip` as SHA-256
`96785927fe859e2fd34512e5db97492242e4f5adb3c9daabba50eaaa1bb7570e`.
The zip was 226,539,176 bytes, extracted with `Expand-Archive` before the smoke;
the extracted bundle contained 3,026 files and 593,945,348 bytes.

The reference machine was GitHub `windows-2025`, Windows Server 2025 Datacenter
10.0.26100, image `win25-vs2026 20261018.275.1`, AMD EPYC 9V45, four logical
CPUs and 16,771,836 kB RAM, in the runner's interactive desktop session. Python
3.12.10 and all five recorded package versions match the historical toolchain
above. Native workflows used the disposable inventory
`D:\a\_temp\invsys-package-smoke\inventory\inventory.db`.

The [Windows package job](https://github.com/theozex4ever/InvSys/actions/runs/39777209762/job/119819603949)
passed both frozen runs (95.8 and 86.7 seconds, including probe overhead; these are
not packaged-launch timings). In **each** run, both Settings folder buttons
called the actual Windows system opener. Explorer exposed a new visible window
at exactly the selected inventory's `backups` path and another at its `exports`
path; the export-recovery folder action was verified too. All six observations
retain the actual path, location URL, window handle, visibility and successful
cleanup separately by run. Native Windows CSV selection and cancellation,
delivered workflows, recovery, themes, keyboard and layout checks passed.

Run 1 left 42 Stock ledger rows and no startup backup. Run 2's startup backup held
exactly those 42 rows, all persisted after restart, and the final inventory held
82 rows; SQLite integrity and selected-inventory isolation passed. Exact asset
hashes matched the frontend artifact. All three firewall profiles were ON and
outbound block rules covered both bundled executables. All six readable startup
failure probes and the no-inventory-write check passed. Linux and macOS package
jobs also passed, including the macOS application seal.

Full diagnostics, build/smoke logs, captures, manifest and checksums are retained
for 90 days in [artifact 12425662009,
`package-evidence-windows-2025`](https://github.com/theozex4ever/InvSys/actions/runs/39777209762/artifacts/12425662009).
The JSON and checksum above preserve the acceptance record in the repository
after that artifact expires; the Windows zip itself is not uploaded.

This establishes Windows package acceptance for ticket #53 on the recorded runner.
It does not establish Windows 10/11 desktop editions, physical/GPU hardware,
non-English Windows, Explorer double-click startup, performance targets or human
operator sign-off. macOS Cocoa-panel/Finder acceptance and the parent retirement
gates remain separate. The evidence-retention commit changes documentation only;
its own CI result must be checked on PR #78 before completion.

## Recorded macOS evidence

Recorded 2026-10-21 by the successful
[`package-smoke (macos-15)` job](https://github.com/theozex4ever/InvSys/actions/runs/39539186064/job/119022829801).
All 18 PR checks passed on head `b0f53bd`. GitHub tested the clean integration
merge `a8ab7e35b43f838f8f4f17fe660bda303f6b07aa` (head `b0f53bd` merged
into main `07798bf`); that exact source commit appears in the bundle manifest.

The unmodified [JSON record](evidence/macos-package-2026-10-21.json) retains the
reference machine, toolchain versions, asset/executable hashes, actual startup
errors and both native run results. The machine was macOS 15.7.9, Apple M1
(Virtual), arm64, three logical CPUs and 7,516,192,768 bytes RAM, in the
runner's logged-in desktop session, using Python 3.12.10.

The extracted application contained 3,314 regular files (534,907,509 bytes).
The [retained checksum](evidence/macos-package-2026-10-21.SHA256SUMS) identifies
`invsys-desktop-darwin-arm64.tar.gz` as SHA-256
`ed3c2997f5b5f664ae1e181bd9a6b9cda470b9c3b1f07504b7b490adf96cb79e`.
The archive is available in that run's `macos-standalone-bundle` artifact for
seven days; diagnostics, screenshots and build output are in
`package-evidence-macos-15` for 90 days.

All five startup failure cases passed, without inventory writes. Both native
runs exited 0 (112.1 and 117.1 seconds, including the probe's waits; these are
not launch-time measurements). The first run left 42 ledger rows and no startup
backup. The second took a startup backup containing those 42 rows, retained them
and finished with 82 rows; SQLite integrity, restart persistence and selected
inventory isolation passed. The actual delivered workflows, Qt import dialogs,
exports, themes, navigation and recovery checks all ran. Asset verification was
byte-for-byte, the final ad-hoc seal passed `codesign --verify --deep --strict`,
and Gatekeeper rejected the application as expected for unsigned distribution.

Visual preview approved by the user on 2026-10-22. The click-through review used
56 actual captures (14 screens, both themes, 1366×768 and 640×480 windows) from
the [passing run for head `a60af91`](https://github.com/theozex4ever/InvSys/actions/runs/39582271771),
whose manifest identifies integration merge `96a4649fb981c5712d00bf4382311b7aafcc0941`.
This records approval of the visual presentation; native Cocoa-panel/Finder
acceptance below and full operational sign-off remain outstanding.

Offline checks used local assets and no HTTP server; the run was not network
isolated. Cocoa panels and real Finder windows were not exercised. Issue #54
remains open for the following native file-operation acceptance:

Use the same archive from the run's `macos-standalone-bundle` artifact and verify
it with `shasum -a 256 -c SHA256SUMS` before extraction. Create a fresh disposable
folder with `mktemp -d /tmp/invsys-macos-acceptance.XXXXXX` and launch with
`--database <that-folder>/inventory.db`, without `--smoke-check`. In Settings,
select and cancel a Parts CSV in the Cocoa panel, then preview and explicitly
import `part_number,description` / `MACOS-ACCEPTANCE,Disposable part`. Export
Parts and open the exports folder in Finder; create a backup and open its folder.
Restart with the same database and verify the Part and startup backup. Record the
tester, date, machine/OS, source commit, archive SHA-256, disposable path and result
of each action alongside the CI JSON. Never use operational inventory for this
fixture.

Gatekeeper approval of a quarantined download remains separately unverified;
unsigned-distribution instructions describe the expected restrictions, not an
executed approval test. Full parity, performance and operator sign-off remain
ticket 18 gates.
