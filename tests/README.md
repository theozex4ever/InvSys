# Inventory Control Quality Gate

Run the automated gate before starting the database migration:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

Manual usability smoke checks:

- Add Part success shows a readable toast.
- Adding the same part again shows a duplicate-part error toast.
- Receive with an invalid quantity shows an error toast.
- Ship with insufficient stock shows an error toast with available and requested quantities.
- Move to the same location shows an error toast.
- Adjust without a reason shows an error toast.
- Dashboard, Parts, BOM, Receive, Ship, Move / Adjust, and History navigation still works after repeated success and error toasts.
