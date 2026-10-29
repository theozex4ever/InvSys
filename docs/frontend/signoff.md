# Package acceptance and operator sign-off record

Ticket #57 (parent #39, which this record does not edit or close). It consolidates
the retained evidence for one named candidate and says exactly which human and
external gates are still open. **No operator sign-off, human accessibility review or
retirement approval is recorded here, and none is inferred.** A closed dependency
issue is not sign-off for #57.

> **Retirement status: blocked.** The original PySide6 application, its launcher and
> its tests stay. Remaining gates are listed under
> [what remains](#what-remains-before-retirement).

## Candidate

The candidate is commit `ec8bc4f20d0d433e695849090287f23426419833` (tree
`78f243b0fd382cd0449541807f7c4e0533eb926d`), the merge of PR #84 into `main`.
[CI run 40809040185](https://github.com/theozex4ever/InvSys/actions/runs/40809040185)
(attempt 1, push to `main`, 2026-10-29 UTC) tested exactly that commit: every job
passed, including **CI gate**, with no re-run and no retried step. CodeQL and Scorecard
passed on the same commit. Because it is a push to `main`, each bundle manifest names
`ec8bc4f` itself (`uncommitted_changes: false`), not a GitHub integration merge.

Evidence tied to the candidate is in
[`evidence/candidate-ec8bc4f/`](evidence/candidate-ec8bc4f/): the unmodified
`package-evidence.json`, `upgrade-evidence.json` and `perf-evidence.json` of each
platform's job, and a [`SHA256SUMS`](evidence/candidate-ec8bc4f/SHA256SUMS) that also
holds each archive's checksum. The JSON hashes were taken from the CI artifacts; a
checkout that rewrites line endings (Windows `autocrlf`) changes them, so verify on a
byte-exact checkout; from inside the directory,
`sha256sum -c --ignore-missing SHA256SUMS` checks the retained JSON files (the list
also names three archives that are not retained, which plain `sha256sum -c` reports as
missing). The macOS archive is the one the run uploaded as
`macos-standalone-bundle` (7-day artifact, SHA-256 `9276fbf0…2d413`, equal to the
build's own checksum). The Linux and Windows archives are not uploaded; only their
checksums survive. Raw captures and logs stay in the run's `package-evidence-*`
artifacts for 90 days; the JSON records are the permanent acceptance record.
`tests/test_candidate_evidence.py` reads the nine records as data and fails if one
names another commit, a dirty tree, a failed step, a single native run, a fixture
other than the one committed in the checkout, or if a retained file no longer matches
`SHA256SUMS`.

**This pull request must not change the candidate.** It adds documentation, evidence
and one test that is not part of any bundle. The commands below must print nothing for any later commit offered as
the same candidate; if they print anything, the evidence belongs to an earlier
candidate and the affected platform checks must be repeated:

```bash
git diff --stat ec8bc4f20d0d433e695849090287f23426419833 HEAD -- \
  inventory_control frontend inventory_desktop.py inventory_visualizer.py \
  requirements-package.txt requirements-package.lock.txt requirements.lock.txt \
  requirements-desktop.txt scripts .github pyproject.toml tests/fixtures
```

`tests/fixtures` is listed because the upgrade rehearsal installs
`tests/fixtures/upgrade/premigration-inventory.sql`. A behavior, asset, dependency, fixture or packaging fix after `ec8bc4f` makes this record
stale for the affected checks; repeat them and record a new candidate rather than
editing this one. The evidence from earlier dated runs elsewhere in these documents
(Windows 2026-10-22, macOS 2026-10-21, performance 2026-10-26, PR #79/#84 upgrade
rehearsals) belongs to earlier commits and is **not** claimed for this candidate.

## Dependencies: what each closed issue establishes

| Issue | What the retained evidence shows | What it does not show |
| --- | --- | --- |
| #54 macOS | Automated macOS package smoke on the candidate (below). The repository owner's comment of 2026-10-29 on #54 reads: "Cocoa-panel and Finder Accepted through manual testing on a Mac. Issues Closed". That is respected and recorded as the owner's acceptance of the Cocoa file-panel and Finder checks in the [macOS procedure](packaging.md#recorded-macos-evidence) | The comment does not name the archive, its SHA-256, the macOS version, the disposable path or each action's result, which that procedure asks to be recorded, nor which build was tested. The comment (2026-10-29T03:01:31Z) predates this candidate's CI archive (`macos-standalone-bundle`, artifact 12869953480, created 03:11:47Z); that shows only it cannot be a test of that downloaded archive, not that the owner tested different bytes. **Whether it applies to this candidate has not been established**, so it is not read as acceptance of this candidate. It is also not workstation sign-off, an accessibility review or Gatekeeper evidence |
| #55 performance | Candidate-specific P01–P05 on all three hosted runners (below); earlier records from 2026-10-26 | Operator judgement of responsiveness; hardware the operator physically uses |
| #56 upgrade/restore | Candidate-specific automated rehearsal on all three runners (below). The closure comment on #56 reads "Migration 15 has been completed. This is a completed issue": it names a different ticket, adds no evidence, and #56's own checklist in the issue body still shows four of five criteria unchecked | Operator-run restore through a file manager, a database from an operator's real inventory, rollback to a *packaged* release (none exists), operator approval. The comment is not read as approval of any of these |

## Acceptance criteria of #57

| Criterion | Status | Basis |
| --- | --- | --- |
| Complete workflow/native smoke checklist on the exact candidate bundles on Windows, Linux and macOS, twice for restart and backup, including CSV/file/folder operations and safe failures | **Automated part met; human part open** | Both native runs on each frozen bundle passed, the second run's startup backup held exactly run 1's 42 ledger rows, five or six readable startup failures per platform, five CSV exports and three imports, backup and folder actions (Windows through real Explorer windows in both runs). macOS import dialogs use Qt's own dialog in the smoke; the Cocoa panel and Finder are covered only by the owner's earlier #54 acceptance, whose mapping to this candidate is not established (see above). The A01–A17 checklist has not been walked by a person on a workstation |
| Consolidate capability classes, automated gates, platform results, performance, upgrade/restore and accessibility; no required capability Missing | **Not met** | Consolidated below. Rows 1, 38 (portion), 47 (portion), 48 (portion), 49 and 50 of the [register](acceptance.md#required-capability-register) remain Missing, Partial or Mixed; the human screen-reader review is absent |
| Actual user or designated-operator sign-off on the intended workstation | **Not obtained** | [Record](#operator-sign-off-record) is blank |
| Document unresolved failures honestly; evidence corresponds to the candidate | **Met for this record** | [What remains](#what-remains-before-retirement); candidate check above. The gate itself stays incomplete |
| Record readiness to retire without closing or editing the parent; sign-off does not authorize release or production data changes | **Not recorded** | Nothing here states readiness: gates above are open. Readiness is the operator's statement in the blank record below, and still would not authorize release publication or production data changes |

## Candidate results per platform

All three package jobs ran the build, the extracted-archive package smoke twice, the
copied-data upgrade rehearsal (four packaged launches) and the performance run, each
on its first attempt and each `passed`. Hosted runners are shared virtual machines
without GPUs. [performance.md](performance.md) records the choice to use them (plus a
local Linux machine) as the measurement machines; #55 itself carries no comment
confirming that designation, so none is claimed here. They are not physical
workstations.

| | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Runner | `ubuntu-24.04`, image `20261026.354.1`, Ubuntu 24.04.5, AMD EPYC 9V45 (4 CPUs, 16 GB), Xvfb, Python 3.12.15 | `windows-2025`, image `win25-vs2026 20261021.278.1`, Windows 10.0.26100, AMD EPYC 9V45 (4 CPUs, 16 GB), interactive session, Python 3.12.10 | `macos-15`, image `macos15 20260907.0337.1`, macOS 15.7.9, Apple M1 virtual, arm64 (3 CPUs, 7.5 GB), logged-in session, Python 3.12.10 |
| Job | [123234823358](https://github.com/theozex4ever/InvSys/actions/runs/40809040185/job/123234823358) | [123234823260](https://github.com/theozex4ever/InvSys/actions/runs/40809040185/job/123234823260) | [123234823200](https://github.com/theozex4ever/InvSys/actions/runs/40809040185/job/123234823200) |
| Bundle | 3,063 files, 634,333,771 B; `invsys-desktop` `aeb07bed…ad7` | 3,026 files, 593,979,385 B; `invsys-desktop.exe` `a4948fbf…e4f` | 3,314 files, 534,951,267 B; `invsys-desktop` `b7a94c32…9f1` |
| Archive SHA-256 | `c36504ef…3a67` | `aed8466c…60b3` | `9276fbf0…d413` |
| Assets | `app.js` `e3e58ed7…eee00f`, `index.html` `9311ff07…a2c`, `style.css` `34176552…6b2c` byte-identical to `frontend-dist` in all three | same | same |
| Startup failure checks | no database, missing assets, folder is a file, path is a directory, non-SQLite, no inventory written: all passed | same, plus an unmapped drive letter | same as Linux |
| Native run 1 / run 2 | exit 0 / exit 0 (76.1 s / 74.2 s) | exit 0 / exit 0 (111.2 s / 97.3 s) | exit 0 / exit 0 (121.1 s / 124.1 s) |
| Startup backup | run 1 none; run 2 held 42 ledger rows | same | same |
| Persistence and isolation | SQLite integrity `ok`; run 1's rows present after run 2; nothing written to `INVSYS_HOME` | same | same |
| Offline | empty network namespace | all three firewall profiles ON, outbound blocked for the launcher and `QtWebEngineProcess.exe` | **not network-isolated** (macOS cannot); local assets, no HTTP server, `check:dist` |
| Native folder opening | recording host | real Explorer windows at the selected inventory's `backups` and `exports` paths, visible, in both runs | recording host; Finder only via the owner's earlier #54 acceptance (candidate mapping not established) |
| Application seal | not applicable | not applicable | ad-hoc, `codesign --verify --deep --strict` passed; Gatekeeper rejected it, as expected unsigned |
| Upgrade rehearsal (nine steps) | passed; launches 73.1 / 73.8 / 72.9 / 73.5 s | passed; 97.0 / 97.2 / 97.7 / 97.8 s | passed; 119.0 / 122.2 / 117.9 / 124.8 s |
| Performance (29 steps, five measured repeats each, two painted frames) | passed, no missing step | passed | passed |

Upgrade rehearsal, all platforms: fixture SHA-256
`3dac3ae7e53c9f38a525ae89c828bbc433ab38d9fb905a727763a455ec188a9d` (8 Parts,
28 ledger rows, 4 shipments, 7 component snapshots), written by the original
application at pinned commit `a03c887dd76056695f81e55d0ff1cac4315ee444`; upgrade,
restart, closed-app restore, reopen, rollback to that release's source tree, roll
forward, selected-path confinement and ten restore failure probes all passed. The
fixture is a scripted historical-code inventory, not an operator's database.

### Candidate performance

Median / slowest of five measured repeats in milliseconds; fixtures of 10,000 Parts,
100,000 transactions and a 1,000-node BOM (18,923,520 B each); every repeat of every
step inside its limit. The remaining steps of the 29 are in the records. These are scripted measurements on the hosted runners, not operator
judgement. Method and caveats: [performance.md](performance.md).

| Step | Limit | Linux | Windows | macOS |
| --- | ---: | ---: | ---: | ---: |
| `P01.search` | 2,000 | 418 / 461 | 439 / 472 | 352 / 372 |
| `P01.sort` | 2,000 | 306 / 310 | 277 / 348 | 246 / 334 |
| `P02.search` | 2,000 | 290 / 318 | 459 / 497 | 408 / 452 |
| `P02.open_record` | 2,000 | 138 / 248 | 289 / 544 | 75 / 160 |
| `P03.open_ship` | 2,000 | 675 / 688 | 833 / 911 | 578 / 609 |
| `P03.review_standard` | 2,000 | 160 / 313 | 320 / 403 | 258 / 354 |
| `P03.review_kit` | 2,000 | 206 / 320 | 383 / 436 | 258 / 336 |
| `P03.review_root` | 2,000 | 589 / 665 | 754 / 847 | 496 / 508 |
| `P04.explore` | 5,000 | 576 / 609 | 793 / 847 | 516 / 553 |
| `P04.labels` | 2,000 | 128 / 138 | 235 / 239 | 173 / 194 |
| `P05.launch` | 10,000 | 1,306 / 1,382 | 1,422 / 1,453 | 1,913 / 1,972 |

The earlier 2026-10-26 records (including the local Linux laptop) remain in
[performance.md](performance.md) for their own commit; no local-machine run exists for
this candidate.

## Automated gates on the candidate

CI run 40809040185, one attempt: Python static analysis (ruff, ruff format, strict
mypy, lock freshness), Tests on Ubuntu 3.12/3.13/3.14, Windows 3.12 and macOS 3.12
(Ubuntu 3.14 leg: 914 passed, 1 skipped; branch coverage 87.42% against the unchanged
85% floor), Frontend build (strict `tsc`, production build, `check:dist`,
reproducibility), Desktop E2E native smoke, Package smoke ×3, Workflow lint, Dependency
audit and **CI gate** all `success`; Dependency review `skipped` (pull-request only).
CodeQL and Scorecard succeeded on the same commit. No threshold was changed. These
results are for `ec8bc4f`; the CI result of the pull request that adds this record
must be read separately.

## Capability classes

After this record the [register](acceptance.md#required-capability-register) has 50
rows: 42 Equivalent (24) or Improved (18), and eight rows that block retirement or
still carry a Missing portion:

| Story | Class | What is missing |
| --- | --- | --- |
| 1 | Missing | Aggregate: the original remains the fallback until every gate passes |
| 37 | Mixed | macOS Cocoa-panel/Finder acceptance for this candidate (or the owner's confirmation that the earlier acceptance still applies) |
| 38 | Intentionally changed, with Missing portions | Operator-run restore through a file manager; rollback to a packaged release (none exists); operator sign-off |
| 45 | Mixed | Same macOS Cocoa-panel/Finder gap; the automated bundles on all three platforms are met |
| 47 | Partial | Operator-designated physical workstations; operator judgement of responsiveness |
| 48 | Mixed | A database copied from an operator's real historical inventory |
| 49 | Missing | Operator sign-off, human accessibility review |
| 50 | Missing | Blocked by every retirement gate |

Story 45 (standalone bundles) moves from Missing to Mixed in this change, and the
macOS portion of story 37 from Missing to a stated gap, on the basis in their rows.
The Windows and Linux portions of 37 and story 46 were already Equivalent.

## Accessibility

Automated and computed review for #51 (contrast, names, focus, keyboard, reduced
motion, reachability) is recorded in
[acceptance.md](acceptance.md#accessibility-review-record) and the native smoke
repeats its audit in every package run above. **No human screen-reader session
(NVDA, JAWS, VoiceOver or Orca) has been performed;** no such tool was available to
this work. Scripted checks do not replace it.

## Operator sign-off record

**Not signed.** The fields below are intentionally blank. Only the user or a
designated operator may complete them, on the intended workstation, with the exact
candidate bundle for that workstation's platform. The agent must not fill, tick or
paraphrase them into approval.

Record by committing this section (or linking an issue comment of the same content)
with the operator's own name and date. Scripted smoke does not substitute for any line.

| Field | Entry |
| --- | --- |
| Operator name and role | _not recorded_ |
| Workstation (platform, OS version, display) | _not recorded_ |
| Candidate commit, archive file and SHA-256 tested | _not recorded_ |
| Disposable database path (never the operational inventory) | _not recorded_ |
| Date | _not recorded_ |

Walked checklist (each against the disposable inventory; reference the scenario in
[acceptance.md](acceptance.md#repeatable-native-and-operator-scenarios)):

- [ ] A01–A05: dashboard and Parts, Receive, standard and BOM Ship, History and trace
- [ ] A06–A09: Part edit/active state, Move, Adjust Count, BOM authoring and explorer
- [ ] A10–A11: five exports, three imports, backup, manual folder opening
- [ ] A12–A13: keyboard, themes, small window, duplicate and ambiguous submissions
- [ ] A14: closed-app restore through the operator's file manager on a copy; reconcile
- [ ] A15 and P05: launch with an explicit database on this workstation; responsiveness
- [ ] Accessibility: screen reader used _(name and version)_; contrast; observations
- [ ] Unresolved objections: _none recorded_

| Statement | Entry |
| --- | --- |
| "I accept this candidate for the workflows above on this workstation." | _not recorded_ |
| "The original application may be retired once the remaining gates pass." | _not recorded_ |

Even a completed record would not authorize publishing a release, installing over or
touching operational inventory, or closing or editing #39.

## What remains before retirement

Human or external (not doable by an agent):

1. Operator sign-off on the intended workstation ([record](#operator-sign-off-record)).
2. A human screen-reader session and contrast observations.
3. **Required:** macOS Cocoa-panel and Finder acceptance mapped to this candidate.
   Either evidence on this candidate's archive (the #54 procedure's record: tester,
   machine and OS, archive SHA-256, disposable path, result of each action), or the
   owner's explicit confirmation that the earlier #54 acceptance remains applicable
   after reviewing the changes between the tested build and `ec8bc4f`. The earlier
   acceptance is respected; only its applicability to this candidate is unproven.
4. Operator-run restore through a file manager on a copy; a copy of the real
   historical inventory for the upgrade rehearsal.
5. Operator judgement of responsiveness on designated physical workstations, if the
   owner wants more than the hosted-runner and earlier local Linux measurements.

Not established by any record, and so out of this gate's claims: Windows 10/11
desktop editions, macOS other than 15.7.9, Intel Macs, Linux distributions other than
Ubuntu 24.04, Gatekeeper approval of a quarantined download, real disk-full or ACL
failures, a packaged earlier release for rollback, installers, signing and release
publication.

Known intermittent behavior to keep visible: the existing native smoke failed
intermittently in earlier runs (Windows drawer and Explorer waits, Linux and macOS
focus checks; see
[packaging.md](packaging.md#recorded-copied-data-upgrade-and-restore-evidence)). None
is root-caused. The candidate run passed every job on its first attempt, which does not
show those races are fixed.

When all of the above is resolved and recorded by their owners, the retirement ticket
can proceed; this record then needs a new candidate entry if any code, asset or
package changed in between.
