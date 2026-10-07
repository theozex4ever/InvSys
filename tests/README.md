# Inventory Control Quality Gate

Run the automated suite from the repository root (configuration is in
`pyproject.toml`; the full CI gate is described in `docs/ci.md`):

```bash
python -m pytest --cov
```

Manual usability smoke checks:

- Add Part success shows a readable toast.
- Adding the same part again shows a duplicate-part error toast.
- Receive with an invalid quantity shows an error toast.
- Ship with insufficient stock shows an error toast with available and requested quantities.
- Move to the same location shows an error toast.
- Adjust without a reason shows an error toast.
- Dashboard, Catalog (Parts / BOM), Stock (Receive / Ship / Move / Adjust), History, and Settings navigation still works after repeated success and error toasts.
