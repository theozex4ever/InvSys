# Security policy

## Supported versions

InvSys is a single-branch application with no maintained release lines. Only
the latest `main` (and the latest release built from it, if any) is supported.
Fixes land on `main`; they are not backported.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's private
vulnerability reporting:
**[Report a vulnerability](https://github.com/theozex4ever/InvSys/security/advisories/new)**
(also reachable from **Security → Report a vulnerability** on this repository).
Do not open a public issue. Include the affected version or commit,
reproduction steps and impact.

## What to expect

InvSys is maintained by one person, so these are targets, not guarantees:

- **Acknowledgement** within a week of the report.
- **Triage** (confirm or decline, with a severity assessment) within 30 days.
- **Fix and coordinated disclosure** within 90 days of the report. Fixes are
  developed in a private advisory and published with it, with credit to the
  reporter unless you prefer otherwise. If a fix needs longer, I will tell you
  why and agree a new date with you rather than disclose silently.

## Scope

InvSys is a local, single-site desktop application with no network service.
Relevant reports include anything that lets crafted input (CSV imports, the
desktop bridge, database files) corrupt inventory records, bypass the
transaction ledger, or execute code, and weaknesses in this repository's CI and
supply chain.

## How the project defends itself

The CI pipeline (see [docs/ci.md](docs/ci.md)) runs CodeQL, bandit rules,
dependency audits, workflow security linting and hash-verified installs on
every pull request. Repository rulesets on the default branch require a pull
request and a single required status check, **CI gate**, which fails if any
upstream job fails. Force-pushes and branch deletion are blocked.

This is a single-maintainer project, so no human approval is required to merge.
What is enforced is the pull request itself and the required CI gate. Beyond
that, the maintainer reviews their own pull requests (often with an independent
automated review), but that is a practice, not a repository rule. CodeQL
findings are reported on each pull request but do not block merging; see
[docs/ci.md](docs/ci.md#one-required-check) for exactly what is enforced.
