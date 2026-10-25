# Packaged performance envelope

Ticket #55 (parent #39). The approved limits are requirements, not measured facts
until a run on a recorded machine says so; this page defines how they are measured,
records what was actually measured, and says what is still missing.

| Scenario | What the operator does | Limit |
| --- | --- | --- |
| P01 | Catalog: search `PERF-00999`, open the Part, clear, filter inactive/active/Low stock, sort by Stock, next page | 2 s per interaction |
| P02 | History: open, search `PERF-RECEIPT-050000`, open the exact record, clear, next 50-row page, filter by type | 2 s per interaction |
| P03 | Ship: open, choose a Part, review a standard shipment (STANDARD lot A × 2), a nested BOM (KIT × 2) and the 1,000-node BOM (PERF-ROOT × 1) | 2 s per interaction |
| P04 | BOM explorer: PERF-ROOT, one build — 1,000 nodes laid out, the first zoom applied; then zoom, pan, fit, select, and zoom to 100 % (where every node's text is laid out) | 5 s to a usable graph, 2 s per graph interaction |
| P05 | Start the packaged executable on the large inventory | 10 s to a usable dashboard |

The limits live in `inventory_control/perf.py` and cannot be passed as options.
Every step has the same rule: **each** measured repeat must meet its limit (one
warm-up, then five measured repeats; the slowest repeat is judged, not the mean). A
step with fewer than five measured repeats is `missing`, never a pass, and any
correctness failure fails the run.

## Fixture

`python -m inventory_control.acceptance --large` builds the frozen fixture through
public inventory operations (about 3.5 minutes on the local machine): exactly 10,000
Parts (451 inactive), 100,000 transactions, a 1,000-node BOM (999 links) in a ten-way tree
rooted at `PERF-ROOT` (900 Leaf materials, depth 3), plus the small `KIT` workflow
data. Fixture construction is never timed. The runner builds a fresh copy per CI leg;
each run records the database SHA-256, size and manifest, so identical content is
distinguishable from a different build (creation timestamps differ between builds).

## Method

`scripts/package_perf.py run` drives the **frozen bundle** (never source) and
`inventory_control/desktop_perf.py` is the probe compiled into it
(`--perf-check launch|workflow`, `--perf-output FILE`; it requires an explicit
disposable `--database`).

* **Usable completion, not backend latency.** A step starts at the operator's action
  (an input event, a click, a form submit) and ends when the *expected, correct* state
  is on screen **and two animation frames have been produced after it**, timed in the
  page with `performance.now()`. Waiting conditions include the content (row counts
  and the footer total against SQLite read directly, the exact record, the Python
  review's allocations, 1,000 laid-out nodes and 900 Leaf rows, an applied zoom).
  `external_ms` is the same step timed by the probe's Python side and adds its
  polling; `api_ms` marks when the last bridge answer arrived, separating Python's
  read and transfer from rendering.
* **P05** is the time from spawning the executable to the probe printing a marker
  once the dashboard shows the right active-Part count, the first page of 10,000
  Parts and History are rendered, nothing is still loading, and navigation and input
  controls are enabled. It is timed on the runner's own monotonic clock, so it
  includes the startup backup, interpreter, Qt and window creation. A cold launch is
  a new process on a pristine copy of the fixture; the first of six is the warm-up
  and is retained but not judged. The OS file cache is warm after that first launch;
  caches are not dropped.
* **Correctness is asserted, not assumed.** Waiting conditions and checks use counts and
  stock read from SQLite independently of the store: the Parts and History footers'
  totals (10,000 Parts, 451 inactive, 100,000 transactions, one `PERF-RECEIPT-050000`,
  the RECEIVE count), the standard review's lot and remainder (lot A: 10 → 8), the KIT
  review's capacity and 14 Leaf units from lot B, the PERF-ROOT review's and explorer's
  Build capacity (the smallest Leaf stock) with the first and last of the 900 Leaf
  rows, and 1,000 laid-out nodes. "Visible focus" in the acceptance wording is only
  checked as far as moving focus to the control and into the opened drawer; the
  rendered focus ring was audited separately (see [acceptance.md](acceptance.md)).
* **Read-only scenarios stay read-only.** The probe compares ledger, balance,
  shipment and BOM counters read from SQLite before and after P01–P04.
* Raw timings of every repeat, min/median/max, the machine, the bundle (hash,
  manifest, source commit), the fixture and the browser version go into the JSON
  record (`perf-evidence.json`, uploaded by the package job for 90 days).

```bash
# Linux shown; the bundle is built and extracted as in packaging.md.
python -m inventory_control.acceptance --large            # optional: the runner builds its own
xvfb-run -a -s "-screen 0 1920x1080x24" \
  python scripts/package_perf.py run --bundle /tmp/invsys-installed/invsys-desktop \
  --workdir /tmp/invsys-perf --evidence /tmp/invsys-perf-evidence.json
```

Run the probe in a window nothing covers. Chromium slows timers to one a second in an
occluded or background window, and pywebview polls for every bridge answer with a timer,
so every bridge call then costs about 1 s. The probe records the page's visibility; for a
local run on a busy desktop add `--disable-background-timer-throttling
--disable-renderer-backgrounding --disable-backgrounding-occluded-windows` to
`QTWEBENGINE_CHROMIUM_FLAGS` (CI's virtual or dedicated sessions need nothing).

Debugging aids for the probe only (optional environment variables):
`INVSYS_PERF_ONLY=P01,P04` runs just those scenarios, and `INVSYS_PERF_HOLD=<seconds>`
keeps the window open after the result is written so a DevTools client can trace it.

## CI

The `package-smoke` job (`ubuntu-24.04`, `windows-2025`, `macos-15`) runs the
performance step after the smoke, on the same extracted bundle, and fails if any
measured repeat is over its limit. These are **shared virtual machines**: timings are
noisy, and a red run is evidence to read (`perf-evidence.json`), not automatically a
regression. The limits are never relaxed to turn it green.

## Bottlenecks found by measuring, and what was done

First complete run on the local machine, source launch, before any change: P01 could
not complete (the renderer passed 2.4 GB showing 10,000 Parts rows and was killed at a
3 GB limit), History search took 2.0–2.1 s, the explorer 6.7–7.4 s, a nested BOM review of
`PERF-ROOT` 2.2–2.5 s and every Part selection on Ship about 0.9 s.

| Bottleneck | Cause (measured) | Change |
| --- | --- | --- |
| History text search 1.1 s in Python | 100,000 rows × 9 columns went through a Python SQL function, and the filter ran twice (count, page) | ASCII values use SQLite's exact ASCII fold; non-ASCII values still fold in Python (`ß`, the Kelvin sign are tested); the match count rides with the page. About 0.5 s |
| Parts page unusable at 10,000 rows | The whole result became table rows; the renderer grew past 2.4 GB | 100 rows per page with Previous/Next and the total in the footer; Python still filters and sorts the whole catalog |
| BOM explorer 3.8–7 s | `fit()` forced layout and paint of about 6,000 `<text>` elements for a graph drawn at its 2 % minimum zoom, where no text is legible | Node and quantity text is not laid out below 25 % zoom (`bomx-far`); it appears when zoomed in. Zoom after render dropped from 0.7 s to 0.03 s |
| Python BOM read 0.77 s | 3 queries per node (links, lazy component Part, Part again) | One query per node, the same inactive-component rule and message. 0.36 s |
| Ship: Part selection 0.9 s | Every selection re-read all 10,000 Parts and rebuilt both option lists | Choosing from the list keeps the lists; Refresh availability and opening Ship reload them |
| Ship: nested BOM review 2.1–2.5 s | The plan (900 + 900 rows) was laid out in the page *and* in the dialog; the dialog's off-screen table was painted | Large plans (>100 lot lines) are collapsed in the page; the dialog's tables skip off-screen rendering (`content-visibility: auto`) |

Changes an operator can see (all are presentation limits; Python still decides what
the data is):

* The Parts page shows 100 rows per page with Previous/Next and the total; filters and
  sorts still apply to the whole catalog.
* Below 25 % zoom the BOM explorer shows boxes without text; the text appears when the
  view is zoomed in (the 1,000-node fit is 2 %). Node names remain in the accessibility
  tree and the inspector.
* A large BOM plan (over 100 lot lines) is collapsed under a "Show … lot allocations"
  summary on the Ship page; the confirmation dialog still shows the whole plan.
  The dialog's tables are not laid out until scrolled near (`content-visibility: auto`),
  so the scrollbar length of the second table is an estimate until it is reached.
* Choosing a Part on Receive or Ship no longer reloads the Part list; opening the page
  or Refresh availability does. A Part created elsewhere appears after that.

The JavaScript size budget (34,000 B gzip) was not changed: the frontend is now
33,950 B, **50 B under it**, so any further frontend change needs an explicit size
decision (see [desktop.md](desktop.md)).

Not changed, and why it matters: opening Ship still reads and builds a 10,000-option
list for the Part (about 1.2 s locally, 0.9 s of it Python's answer and transfer). It
passes today but is the first limit a slower workstation will hit; a searchable
picker would be the fix, and it changes every stock workflow, so it is a separate
decision, not an incidental performance patch.

## Results

Recorded 2026-10-25 by `scripts/package_perf.py` on the frozen bundles. Every record has
`result: passed`, no probe error, no missing step and no warm-up over its limit. The
unmodified JSON records and their [checksums](evidence/performance-2026-10-25.SHA256SUMS)
are in `evidence/`: [Linux hosted](evidence/performance-linux-hosted-2026-10-25.json),
[Windows hosted](evidence/performance-windows-hosted-2026-10-25.json),
[macOS hosted](evidence/performance-macos-hosted-2026-10-25.json) and
[Linux local](evidence/performance-linux-local-2026-10-25.json). The hosted records are
also in each job's `package-evidence-<os>` artifact for 90 days.

### Hosted runners (CI)

[CI run 40188450902](https://github.com/theozex4ever/InvSys/actions/runs/40188450902),
PR #81 code head `21fd08d347037f2f539488bad07bdb65dbbdd62b`; every job passed. Each bundle
manifest names the GitHub integration merge `4109e0702df8924337490e03e101c393dd740bc3`
(that head merged into `main` `249454e`), which has exactly the head's tree
(`16ecf7a8cc15`) and `uncommitted_changes: false`. Later commits on the PR change only
documentation and these evidence files.

| Platform | Machine | Bundle | Fixture (built by that job through the public API) |
| --- | --- | --- | --- |
| Linux | `ubuntu-24.04` image `20261023.334.3`: AMD EPYC 9V45, 4 logical CPUs, 16 GB, Ubuntu 24.04.5, glibc 2.39, Xvfb 1920×1080 (window 1366×768), Python 3.12.15 | 3,063 files, 634,324,744 bytes, `invsys-desktop` `e73d6d55c29e…` | database `c9b2fe1538e4…` |
| Windows | `windows-2025` image `win25-vs2026 20261021.278.1`: AMD EPYC 7763, 4 logical CPUs, 16 GB, Windows Server 2025 10.0.26100, interactive session at 1024×768 (window 1028×749), software rendering, Python 3.12.10 | 3,026 files, 593,970,355 bytes, `invsys-desktop.exe` `9de932bbc9dd…` | database `a0ee2819008a…` |
| macOS | `macos-15` image `macos15 20260907.0337.1`: Apple M1 (virtual), 3 logical CPUs, 7.5 GB, macOS 15.7.9, logged-in session at 1024×768 (window 1024×653), Python 3.12.10 | 3,314 files, 534,942,176 bytes, executable `1e19e9e1e7fb…` | database `ac0cc940978a…` |

All fixtures are 18,923,520 bytes with 10,000 Parts and 100,000 transactions; the hashes
differ because generated timestamps do. PyInstaller 6.22.3, PySide6/Qt WebEngine 6.11.2
(Chrome 140) and pywebview 6.2.1 everywhere.

### Local workstation

The user's laptop: Intel Core i7-7700HQ (8 logical CPUs), 8 GB, Ubuntu 24.04.5, Linux
7.0.0-38, glibc 2.39, Python 3.12.3. Bundle built from the clean commit `21fd08d34704`
(`uncommitted_changes: false`; 3,047 files, 604,338,138 bytes, `invsys-desktop`
`aa8d1d566cad…`), extracted, and measured under a virtual X server (Xvfb 1920×1080,
window 1366×768) with memory capped at 3 GB, serialized with other jobs, fixture built
by the runner in 146 s (database `d5d1effa9fb5…`). **Not** measured on the physical
desktop session: with the screen locked or the window covered, Chromium throttles timers
and every bridge call costs about a second (probe runs on the locked screen
showed exactly that, and Xvfb removed it); such runs are invalid, not slow.

### Timings

Median / slowest of the five measured repeats, in milliseconds (every repeat of every
step, including those not shown, is in the records):

| Step | Limit | Linux | Windows | macOS | Local Linux |
| --- | ---: | ---: | ---: | ---: | ---: |
| `P01.search` | 2,000 | 342 / 380 | 607 / 721 | 353 / 405 | 475 / 534 |
| `P01.sort` | 2,000 | 245 / 295 | 501 / 569 | 240 / 252 | 424 / 497 |
| `P02.search` | 2,000 | 273 / 277 | 958 / 967 | 504 / 538 | 568 / 580 |
| `P02.open` | 2,000 | 245 / 331 | 640 / 691 | 284 / 325 | 464 / 531 |
| `P03.open_ship` | 2,000 | 601 / 665 | 1,084 / 1,169 | 508 / 616 | 950 / 997 |
| `P03.review_standard` | 2,000 | 253 / 260 | 592 / 716 | 245 / 256 | 554 / 606 |
| `P03.review_kit` | 2,000 | 195 / 277 | 725 / 762 | 232 / 237 | 456 / 571 |
| `P03.review_root` | 2,000 | 545 / 568 | 1,386 / **1,435** | 506 / 516 | 1,124 / 1,233 |
| `P04.explore` | 5,000 | 490 / 533 | 1,421 / 1,666 | 524 / 556 | 1,047 / 1,104 |
| `P04.zoom` | 2,000 | 19 / 27 | 96 / 176 | 74 / 108 | 16 / 32 |
| `P04.labels` | 2,000 | 118 / 124 | 498 / 645 | 157 / 176 | 439 / 525 |
| `P05.launch` | 10,000 | 1,220 / 1,246 | 2,063 / 2,359 | 1,657 / 1,787 | 2,212 / 2,418 |

The tightest step everywhere is the nested BOM review or opening Ship (the 10,000-option
Part list): Windows `review_root` 1.44 s of 2 s, Windows `open_ship` 1.17 s, local
`review_root` 1.23 s. Those are the first limits a slower workstation would reach.
Windows is consistently about 2–3× the others (software rendering on a shared VM).

### History of this work's evidence

Two things happened on the way that explain the record rather than hide it:

* A first CI attempt failed on Windows in the existing explorer keyboard smoke (not in
  this probe): a one-line hint addition to the explorer changed the page height and
  toggled Windows' classic scrollbar, shifting the fitted graph. Linux and macOS use
  overlay scrollbars and passed. The line was reverted.
* A review found vacuous probe assertions and a missing measurement (the cost of laying
  out node text when zooming in). The checks were strengthened (they compare with
  SQLite, see Method) and `P04.labels` was added; hosted and local evidence was
  re-recorded on the commit above, replacing records from the earlier probe.

## What this does and does not establish

Established where a record exists: the listed machine, bundle and fixture meet the
limits for the scripted scenarios, with correctness checked against SQLite.

Not established:

* Hardware designated by an operator. The user's decision is to use the hosted
  `ubuntu-24.04`, `windows-2025` and `macos-15` runners plus this local Linux
  machine; none is a physical Windows or macOS workstation, none has a GPU, and
  hosted runners are shared VMs.
* Cold-cache launch, other displays or scaling, battery power, antivirus on
  Windows, Intel Macs, other Linux distributions or Windows 10/11 desktop editions.
* Catalogs or histories larger than the frozen fixture, or BOMs that are deeper than
  depth 3 (the large tree measures breadth).
* Human or operator judgement of responsiveness, screen-reader behaviour, and any
  sign-off (#57). Scripted timing is not operator acceptance.
