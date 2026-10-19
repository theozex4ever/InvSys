# Manual PySide6 smoke checks

CI executes the automated tests with `pyproject.toml` configuration. Follow
[AGENTS.md](../AGENTS.md) to push and wait for green CI; local test execution
is optional. See [CI guidance](../docs/ci.md) for failure reporting and optional
local commands. When manual verification of the original application is requested,
check:

- Add Part success shows a readable toast.
- Adding the same part again shows a duplicate-part error toast.
- Receive with an invalid quantity shows an error toast.
- Ship with insufficient stock shows an error toast with available and requested quantities.
- Move to the same location shows an error toast.
- Adjust without a reason shows an error toast.
- Dashboard, Catalog (Parts / BOM), Stock (Receive / Ship / Move / Adjust), History, and Settings navigation still works after repeated success and error toasts.
