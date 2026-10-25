# Packaged performance envelope

Ticket #55 (parent #39). The approved limits are requirements, not measured facts
until a run on a recorded machine says so; this page defines how they are measured,
records what was actually measured, and says what is still missing.

| Scenario | What the operator does | Limit |
| --- | --- | --- |
| P01 | Catalog: search `PERF-00999`, open the Part, clear, filter inactive/active/Low stock, sort by Stock, next page | 2 s per interaction |
| P02 | History: open, search `PERF-RECEIPT-050000`, open the exact record, clear, next 50-row page, filter by type | 2 s per interaction |
| P03 | Ship: open, choose a Part, review a standard shipment (STANDARD lot A × 2), a nested BOM (KIT × 2) and the 1,000-node BOM (PERF-ROOT × 1) | 2 s per interaction |
| P04 | BOM explorer: PERF-ROOT, one build — 1,000 nodes laid out, the first zoom applied; then zoom, pan, fit, select | 5 s to a usable graph, 2 s per graph interaction |
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

Debugging aids for the probe only (all optional environment variables):
`INVSYS_PERF_ONLY=P01,P04` runs just those scenarios, `INVSYS_PERF_CSS`/
`INVSYS_PERF_EVAL` inject a style rule / evaluate a script after the launch, and
`INVSYS_PERF_HOLD=<seconds>` keeps the window open so a DevTools client can trace it.

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

The JavaScript size budget (34,000 B gzip) was not changed: the frontend is now
33,966 B, **34 B under it**, so any further frontend change needs an explicit size
decision (see [desktop.md](desktop.md)).

Not changed, and why it matters: opening Ship still reads and builds a 10,000-option
list for the Part (about 1.2 s locally, 0.9 s of it Python's answer and transfer). It
passes today but is the first limit a slower workstation will hit; a searchable
picker would be the fix, and it changes every stock workflow, so it is a separate
decision, not an incidental performance patch.

## Results

### Linux, local machine (frozen bundle)

Recorded 2026-10-24 by `scripts/package_perf.py` on the user's workstation, record
[`evidence/performance-linux-local-2026-10-24.json`](evidence/performance-linux-local-2026-10-24.json).

| Item | Value |
| --- | --- |
| Machine | Intel Core i7-7700HQ (8 logical CPUs), 8 GB RAM, Ubuntu 24.04.5, Linux 7.0.0-38, glibc 2.39, X11 session at 1920×1080, 1366×768 window, device pixel ratio 1, no GPU tuning |
| Software | Python 3.12.13 bundle (PyInstaller 6.22.3, PySide6/Qt WebEngine 6.11.2 = Chrome 140, pywebview 6.2.1), reduced motion forced as in CI |
| Bundle | 3,047 files, 604,336,491 bytes, `invsys-desktop` SHA-256 `fbb4ce83…`; built from commit `589c2adb2bb5` **with uncommitted test and coverage-configuration edits** (`uncommitted_changes: true`; nothing in the bundle differed) |
| Fixture | the large fixture above, database SHA-256 `d7b9dc95…`, 18,923,520 bytes, on the workstation's disk |
| Conditions | the workstation was in normal use (a browser, an editor and other agents' jobs); runs were serialized and capped at 3 GB memory; warm file cache after the first launch |
| Result | **every step passed** (all 28 steps, every repeat); no probe error |

| Step | Max of 5 measured repeats (ms) | Median (ms) | Limit (ms) |
| --- | ---: | ---: | ---: |
| P01 slowest (search, clear, filters, sort) | 557.7 | 437.3 | 2,000 |
| P02 slowest (search) | 753.8 | 545.1 | 2,000 |
| P03 `open_ship` | 1,267.8 | 1,191.9 | 2,000 |
| P03 `review_root` (PERF-ROOT) | 1,791.9 | 1,520.1 | 2,000 |
| P04 `explore` (1,000 nodes + first zoom) | 1,746.5 | 1,690.4 | 5,000 |
| P04 slowest graph interaction | 33.1 | 32.0 | 2,000 |
| P05 `launch` (spawn → usable) | 2,582.2 | 2,315.3 | 10,000 |

The heaviest margin is the nested-BOM review (1.79 s of 2 s). Every raw timing is in
the record.

CI results: see below.

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
