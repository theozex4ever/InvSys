# Manual PySide6 smoke checks

The automated gate is in the repository `CLAUDE.md` and README. After UI changes
to the original application, also check:

- Add Part success shows a readable toast.
- Adding the same part again shows a duplicate-part error toast.
- Receive with an invalid quantity shows an error toast.
- Ship with insufficient stock shows an error toast with available and requested quantities.
- Move to the same location shows an error toast.
- Adjust without a reason shows an error toast.
- Dashboard, Catalog (Parts / BOM), Stock (Receive / Ship / Move / Adjust), History, and Settings navigation still works after repeated success and error toasts.
