# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub:
**Security → Report a vulnerability** on this repository. Do not open a public
issue. Include the affected version or commit, reproduction steps and impact.

You can expect an acknowledgement within a week. Fixes are developed in a
private advisory and released with credit to the reporter unless you prefer
otherwise.

## Scope

InvSys is a local, single-site desktop application with no network service.
Relevant reports include anything that lets crafted input (CSV imports, the
desktop bridge, database files) corrupt inventory records, bypass the
transaction ledger, or execute code, and weaknesses in this repository's CI and
supply chain.

## How the project defends itself

The CI pipeline (see [docs/ci.md](docs/ci.md)) runs CodeQL, bandit rules,
dependency audits, workflow security linting and hash-verified installs on
every pull request, and a single required gate blocks merging on any failure.
