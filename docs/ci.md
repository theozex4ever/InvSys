# CI design

InvSys is a single-operator inventory system whose correctness rules — every
balance change has a transaction, stock never goes negative, BOM shipments are
reviewed and atomic — live in code. The pipeline's job is to make it impossible
to merge a change that breaks those rules, the build, or the supply chain, and
to make every failure explain itself.

## Shape

```text
pull_request / push main / merge_group / weekly
│
├─ Workflow lint ─────────── actionlint + shellcheck, zizmor (pedantic)
├─ Python static analysis ── ruff lint, ruff format, mypy --strict, lock freshness
├─ Tests ×5 ──────────────── Ubuntu 3.12 · 3.13 · 3.14, Windows 3.12, macOS 3.12
├─ Frontend build ─────────► dist artifact ─► Desktop E2E (native smoke, Xvfb)
├─ Dependency audit ──────── pip-audit (hash-locked set), npm audit
├─ Dependency review ─────── PR-only: blocks newly introduced vulnerable deps
│
└─ CI gate ◄── needs all of the above; the only check branch protection requires

CodeQL (separate workflow) ── python, JS/TS, actions · its own required check
```

Independent jobs run in parallel. Measured on this PR: the Windows test leg is
the slowest (about 2.5 minutes), frontend → desktop E2E takes under two, and the
whole run reports in under three minutes.

## The gates and what each one catches

| Gate | Fails when | Why it exists here |
| --- | --- | --- |
| **ruff** (curated families, see `ruff.toml`) | likely bugs, bandit security smells, blind `except`, broad `pytest.raises` | Each disabled rule has a written reason. Enabling `PT011` exposed tests that would pass on the *wrong* validation error. |
| **ruff format** | unformatted code | No style review in PRs. The one-time reformat is in `.git-blame-ignore-revs`. |
| **mypy --strict** on the domain core | type errors in store, ledger, bridge, ORM, import/export, backup, launchers | The core owns every inventory invariant. The Qt widget layer is excluded (PySide6 enum stubs are noisy); that list may only shrink. |
| **Lock freshness** | `scripts/lock.sh` would change a lock file | Manifest edits cannot merge without the matching lock; hand-edited locks are rejected. |
| **pytest**, random order | a failing or order-dependent test | `pytest-randomly` prints its seed in the header; rerun with `--randomly-seed=<seed>` to reproduce an ordering. |
| **Warnings are errors** | any warning, e.g. `ResourceWarning` | This is how a real leak was found: `with sqlite3.connect()` never closes, which locks backup files on Windows. |
| **Coverage floor** (85 % branch) | coverage drops below the floor | A ratchet: raise it as coverage grows, never lower it to pass. |
| **Per-test timeout** (60 s) | a hung Qt event loop | Fails one test fast instead of burning the 20-minute job. |
| **Hermetic tests** | the run writes anything into the checkout | Tests once created `data/inventory.db`, the *operational* database path. `INVSYS_HOME` now points them at a throwaway directory. |
| **OS matrix** | Windows/macOS-only failures | It is a desktop app; operators are unlikely to run Ubuntu. |
| **npm ci --ignore-scripts** + `npm audit signatures` | install hooks, unsigned or tampered packages | No dependency code runs during install. |
| **Strict tsc** | type errors incl. unchecked indexing, inexact optionals | `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` and friends. |
| **check-dist** | missing/empty assets, any network URL, gzipped size over budget, module scripts | The desktop shell loads `file://` with no server: a CDN link or `type="module"` would break offline use. |
| **Reproducible build** | two builds of one commit differ | Cheap proof the artifact depends only on the source and lockfile. |
| **Desktop E2E** | any step of the native smoke | Real pywebview + Qt WebEngine against the *exact* bytes the frontend job built: receipts, shipments, BOM review, reconciliation after lost responses, both themes, four viewports, keyboard focus, restart persistence, a startup backup on the second launch. Screenshots are uploaded. |
| **pip-audit / npm audit** | a known vulnerability anywhere in the locked trees | Full-tree view, also on the weekly schedule. |
| **Dependency review** | a PR *adds* a vulnerable dependency | Diff view with OpenSSF Scorecard data for new packages. |
| **actionlint** | invalid workflow syntax, expressions, shell bugs | Workflows are code. |
| **zizmor** (pedantic) | template injection, excessive permissions, unpinned actions, credential persistence, cache poisoning | The pipeline itself is attack surface. |
| **CodeQL** | new code-scanning alerts in changed code | Caught a TOCTOU pattern and a possibly-uninitialized variable while this pipeline was being built. |

## Supply-chain hardening

- **Actions pinned to full commit SHAs** with the version in a comment. Tags are
  mutable; SHAs are not. Dependabot updates the SHA and the comment together.
- **`permissions: {}`** at workflow level; each job requests only what it uses.
  Only CodeQL and Scorecard can write (`security-events`), only Scorecard can
  mint an OIDC token.
- **`persist-credentials: false`** on every checkout, so later steps cannot
  reuse the token from `.git/config`.
- **Hash-locked Python.** `requirements.lock.txt` and `requirements-ci.lock.txt`
  pin every transitive dependency with sha256 hashes for Linux, Windows and
  macOS (`uv pip compile --universal`). CI installs with `--require-hashes`, so
  a re-published wheel fails instead of running.
- **Separate tool environment.** Linters and auditors come from
  `requirements-ci.txt`, isolated from the application's dependency tree.
- **Seven-day cooldown** on Dependabot updates: compromised releases are
  usually yanked within days.
- **Chromium sandbox kept on** in the E2E job: the job re-enables unprivileged
  user namespaces on Ubuntu 24.04 rather than passing `--no-sandbox`.

## One required check

Branch protection requires only **CI gate**, pinned to the GitHub Actions app
(`integration_id` 15368) so a commit status posted by anything else cannot
satisfy it. The gate fails unless every upstream job succeeded; only
`dependency-review` may be skipped, and only on non-PR events. Adding or
re-matrixing a job therefore never silently drops it from merge requirements —
the classic failure of listing matrix job names in branch protection.

The proposed ruleset is in [`.github/rulesets/main.json`](../.github/rulesets/main.json):
default branch only; pull requests with resolved threads; **CI gate** passing
on an up-to-date branch; no new high-severity CodeQL alerts; no force-push or
deletion. Apply or update it with:

```bash
gh api repos/theozex4ever/InvSys/rulesets --method POST --input .github/rulesets/main.json
# or, to update an existing ruleset in place:
gh api repos/theozex4ever/InvSys/rulesets/<id> --method PUT --input .github/rulesets/main.json
```

Repository settings that complete the picture (Settings → Code security):
dependency graph and Dependabot alerts (needed by dependency review), secret
scanning with push protection (already on), and private vulnerability
reporting (used by [`SECURITY.md`](../SECURITY.md)).

## Scheduled runs

| Workflow | When | Purpose |
| --- | --- | --- |
| CI | weekly on `main` | New CVEs in unchanged locks; runner-image drift. |
| CodeQL | weekly | New queries against unchanged code. |
| Scorecard | weekly and on ruleset changes | Public supply-chain score for the README badge. |
| Dependency canary | weekly | Resolves the *newest* versions the ranges allow, on the newest Python and Node, and runs lint, types, tests and the frontend build. Red means the next `scripts/lock.sh --upgrade` needs work first; it never blocks PRs. |

## Trade-offs and deliberate omissions

- **Audits block PRs.** A CVE disclosed today in an untouched dependency turns
  every PR red until the lock is bumped. That is the intended "stop the line"
  behaviour for a small codebase where the fix is usually one
  `scripts/lock.sh --upgrade-package <name>`. If a fix does not exist yet, add a
  dated `--ignore-vuln <ID>` with a comment to the audit step.
- **Python is not in Dependabot.** Its pip updater cannot regenerate a
  universal hash-pinned lock faithfully. The canary plus `scripts/lock.sh`
  replace it; Dependabot alerts still watch the lock.
- **No path filters.** Every job runs on every PR. The whole pipeline costs a
  few minutes, and conditional jobs complicate the required-check story.
- **The Qt widget layer is excluded from mypy**, and DTZ (aware datetimes) is
  not enabled: local wall-clock timestamps are a domain decision whose change
  is a data migration, not a lint fix.
- **No CODEOWNERS or required approvals.** One maintainer cannot approve their
  own PR; the ruleset requires the PR flow and green checks instead.
- **No mutation testing or E2E coverage merge yet.** Both are natural next
  steps for `ledger.py`, the single writer of balances and transactions.

## Running the gates locally

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock.txt
ruff check . && ruff format --check . && mypy
python -m pytest --cov                    # random order, warnings as errors, coverage floor
npm ci --ignore-scripts --prefix frontend
npm run check --prefix frontend && npm run build:assets --prefix frontend
npm run check:dist --prefix frontend
scripts/lock.sh && git diff --exit-code   # needs uv; locks must not change
```

The native E2E needs a display (or `xvfb-run -a`) and a disposable database:

```bash
python inventory_desktop.py --database /tmp/invsys-smoke/inventory.db --smoke-check
```

## Proving a gate fails

A gate that has never failed is untested. To check that a red job blocks the
merge, open a throwaway PR adding `tests/test_ci_probe.py` with
`def test_ci_probe(): assert False`; the matrix legs fail, **CI gate** turns
red, and the merge button is disabled. Close the PR without merging.
