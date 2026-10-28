# Cutover, restore and rollback

How an existing inventory moves to the replacement desktop packages, how it is
restored from a backup, and how to go back. Parent spec: #39; this is ticket #56.
Everything here is a **closed-application procedure done by an operator** on files.
The application has no restore feature, no database picker and never moves data: the
database is whatever `--database` names (source launches without it keep
`data/inventory.db` under the checkout or `INVSYS_HOME`).

Nothing in the replacement changes the database schema. The pre-migration fixture was
written by the original application as it was before the replacement existed (commit
`a03c887`, see [Last known-good release](#last-known-good-release-rehearsed)), and its
schema is byte-identical to the one a new application creates; the tests fail if that
ever stops being true. A migration of the presentation layer therefore has no data
conversion step, and a new bundle opens an existing inventory as it is.

## Words used here

- **Operational inventory**: the real database file operators work in. Acceptance
  and rehearsals never touch it.
- **Selected database**: the file passed with `--database`. Its backups (`backups/`),
  exports (`exports/`) and logs (`logs/`) are in the same folder.
- **Last known-good artifact**: the previous bundle (archive and unpacked folder, or
  the checkout commit for a source launch) that was working against this inventory,
  kept until the new one has been used successfully. Record its file name and
  SHA-256 in the cutover log. (No packaged release exists before the replacement;
  see [Last known-good release](#last-known-good-release-rehearsed).)
- **Startup backup** (`inventory-YYYYMMDD-HHMMSS-startup.db`): taken at every launch
  *before* the database is opened, so it is the inventory exactly as the previous
  session left it. **Manual backup** (`...-manual.db`): taken from Settings. Only the
  newest 20 files are kept. Not every backup is verified: the new application's Create
  backup reopens and integrity-checks the copy and removes it if it fails, but the
  original application's Settings backup only copies the file (falling back to a raw
  file copy if SQLite's backup fails) and reports success, and startup backups of
  either application are not checked. [Verify a backup yourself](#verify-a-backup).

## Verify a backup

A backup is only a recovery path once it has been checked. Use any of these on a
**copy** or on the backup itself (they never change it):

- With a checkout of this repository and Python 3.12:
  `python scripts/upgrade_rehearsal.py verify-backup <backup file>`. It inspects a
  scratch copy of the file (with any `-wal`/`-shm` beside it), so the backup is never
  changed, checks SQLite integrity, the required tables and foreign keys, and that
  every balance and shipment agrees with the ledger. It prints `verified` with the Part,
  Lot, ledger and shipment counts (compare them with the dashboard) and exits 0, or lists
  the problems and exits 1. This is the check for a backup made by the original
  application.
- Without Python: copy the backup into a new disposable folder, launch the accepted
  bundle with `--database` pointing at the copy, and check Parts, a stocked Part's Lots,
  History's last transaction and one BOM shipment. Close it and discard the folder.
- Where the `sqlite3` shell is installed, `PRAGMA integrity_check;` must print `ok`. This
  checks the file's structure only, not the ledger.

File size or a success message alone verifies nothing.

## Cutover

Do this with the operational inventory only after the bundle for your platform has
passed its package smoke and the upgrade rehearsal (see [evidence](#evidence)).

1. **Close every InvSys program**, including the original PySide6 application. Check
   the task manager/activity monitor: a program still running holds the database.
2. **Take and verify a backup.** Open the *current* (old) release, Settings > Create
   backup, close the program, then [verify the file](#verify-a-backup): do not rely on
   the old release's success message. Also copy `inventory.db` to storage outside the
   data folder using the file manager. Note the date, the Parts count the dashboard
   showed and the verification output.
3. **Keep the last known-good artifact**: leave the old bundle where it is (or
   archive it) and write its name and SHA-256 down. Do not delete it.
4. **Install the accepted bundle** by extracting its archive into a **new** folder
   ([Linux](packaging.md#install-and-run-linux), [Windows](packaging.md#install-and-run-windows),
   [macOS](packaging.md#install-and-run-macos)). Check the archive's SHA-256 against
   the build record first. Never extract over the old one.
5. **Select the existing inventory explicitly**: launch with `--database <path to
   the operational inventory.db>`. A bundle refuses to start without it, and nothing
   is copied or relocated. Make a shortcut with that argument.
6. **Validate representative reads before resuming work:**
   - Settings shows the database path you expect and its `backups` folder beside it;
     the startup backup of this launch is listed (it was taken before the database was
     opened, so [verify it](#verify-a-backup) if you want certainty).
   - The dashboard's Parts and Low stock figures match what step 2 recorded.
   - Open one stocked Part and compare its Lot and Location balances with the old
     release's screen.
   - In History, find the last transaction made before the cutover, and open one
     BOM shipment: its consumed components (per Lot) must be the ones recorded then.
7. Resume work. Keep the old artifact until you are comfortable (at least one full
   working period), then record the decision to retire it.

If any check in step 6 disagrees, **stop**: close the application, keep the files
as they are, and follow [Rollback](#rollback).

## Restore from a backup (closed application)

Restore replaces the inventory with an older state. Stock changes made after the
backup exist only in the displaced file, so restoring is always followed by
[reconciliation](#reconcile-ledger-entries-after-restoring-an-older-backup).

1. **Before closing the application**, if it still opens (this export step is not
   part of the automated rehearsal): Settings > Export
   Transactions and Export Shipments, and keep the files. They list every ledger entry
   and shipment the restore is about to remove from the live inventory.
2. **Close every InvSys program.** On Windows a program that still holds the file makes
   step 4 fail with a "being used by another process" error, which is the safe
   outcome. Linux and macOS do **not** stop you from replacing a file a running
   program has open: confirm the application is closed yourself.
3. **Choose the backup** in the selected inventory's `backups/` folder. A startup
   backup is the inventory as it was before that launch; a manual backup is as it was
   when the button was pressed. Never use a backup from another inventory's folder.
4. **Set the current database aside, never delete it.** In the database folder create
   `restore-aside/<date-time>/` and **move** (not copy) `inventory.db` and, if present,
   `inventory.db-wal` and `inventory.db-shm` into it. The write-ahead files belong to
   the displaced database; left behind they would be applied to the restored one.
5. **Copy** (not move) the chosen backup into the database folder under the name
   `inventory.db`. Leave the backup where it is.
6. **Launch with the same `--database`** and check Parts, Lots, History and the
   startup backup that this launch took (it must be the restored state).
7. **Reconcile** before resuming work.

To undo a restore: close the application, set the restored `inventory.db` (and any
sidecars) aside, and move the displaced files back together.

### What failure looks like

The rehearsal's restore helper follows exactly these steps and is run against each
failure below on every platform where the situation can occur (the read-only folder
applies on Linux and macOS, a program holding the file open on Windows; a full disk
is simulated by an injected error, and failing to put the files back is covered by a
unit test rather than the native rehearsal); it checks the database is byte-for-byte
unchanged afterwards. The messages are the helper's; doing the steps by hand, the same
situations show up as the file manager's own errors.

| Situation | Outcome |
| --- | --- |
| backup missing, not a file, not SQLite, truncated, or not an InvSys inventory | refused before anything moves: "Nothing was changed." |
| the backup is the live database itself | refused |
| the aside folder cannot be created (a file in the way, read-only folder) | refused before anything moves |
| the database cannot be moved aside (read-only folder; on Windows a program still has it open) | "Restore failed: Permission denied ..." and nothing was changed |
| the copy fails after the database was moved aside (disk full) | the displaced files are moved back: "The previous database was put back" |
| the copy fails and its staging file (`inventory.db.restoring`) cannot be removed either | the displaced files are still put back first; the message also names the staging file to delete by hand |
| the displaced files cannot be put back either | the message names the aside folder holding them; copy them back by hand |

Operators doing this by hand: if a step fails, stop, and put anything already moved
back before trying again. An inventory file with a leftover `.restoring` or without
its `-wal` partner is a sign of an interrupted attempt.

## Rollback

There are two different things to go back to; choose by what is wrong.

**The new application misbehaves, the data is fine** (nothing was written, or what
was written is correct). Close the new application and start the last known-good
artifact on the same inventory. Take a backup first. No data step is needed because the
schema is unchanged: whatever the new application recorded stays in the ledger and the
last known-good release reads it ([rehearsed](#last-known-good-release-rehearsed)).
Where the old release keeps its inventory depends on which release it is: the original
application at the rehearsed commit has no database option and uses `data/inventory.db`
beside its code (so point the new bundle's `--database` at that file and nothing needs
moving); a later source checkout of the original application uses `INVSYS_HOME` or its
default `data/` folder. Each release writes its startup and manual backups to its own
`backups/` folder, which for the rehearsed release is `backups/` beside `data/`, not the
`data/backups` folder the new application uses for the same inventory. Verify the
backups of the release you are about to use before relying on them.

**The data is wrong** (an import, a mistaken operation, a damaged file). Restore a
backup as above. This is a data rollback and always needs reconciliation.

An older backup must **never** be placed over later ledger activity without that
reconciliation: the displaced database is the only record of the work done since.

## Last known-good release (rehearsed)

The artifact the rehearsal rolls back to is the original PySide6 application at commit
`a03c887dd76056695f81e55d0ff1cac4315ee444` (PR #5, 2026-09-28), the last commit before the
pywebview frontend. It is pinned in `scripts/last_known_good.py` and unpacked from git
history (`git archive`), so the rehearsal needs the repository's full history (CI checks
it out with `fetch-depth: 0`; a shallow clone fails with an instruction to unshallow).
It is a **source tree** run as `python inventory_visualizer.py`, not a packaged release:
none exists, and none is invented here. Its code and tests are the repository's own
history at that commit; its dependencies are the ones the rehearsing interpreter has.

The rehearsal keeps the operator's inventory where this release keeps it,
`<release>/data/inventory.db`, and points the replacement at that file with
`--database`; nothing is copied. After the replacement has been launched twice, the
release is started on the same file by `last_known_good.py rollback-probe`, in a child
interpreter that only sees the release's code (`python -I`), with Qt's offscreen platform:
it runs the release's own `inventory_control.app.main` (startup backup, then the real main
window, whose views read the whole inventory), then works through the release's own store
(receive, move, standard ship, nested-BOM ship with a reviewed plan, count correction,
manual backup). The rehearsal then checks that the release read every Part, ledger row,
shipment and per-Lot component snapshot the replacement had left, that its startup backup
equals the inventory as the replacement left it, that no earlier record changed, that the
schema is unchanged, that ledger, balances and snapshots still reconcile with the
release's new rows, and launches the replacement once more on the result.

Not covered: the release's window is created but not driven, and the replacement's data
after the release's work is read back by one launch, not a long working period.

## Reconcile ledger entries after restoring an older backup

Goal: every real-world stock change since the backup ends up recorded again, each
through a normal workflow (so each gets its ledger row), or is knowingly dropped.

1. Copy the displaced set **together**: `inventory.db` and its matching
   `inventory.db-wal` and `inventory.db-shm`, all three, from the aside folder into a new
   disposable folder. After a crash the newest committed entries can live only in the
   `-wal` file, so a lone `inventory.db` copy silently omits them. Never open the files in
   the aside folder themselves.
2. List what the restore removed, by **record identity, not by time**:
   - With a checkout and Python: `python scripts/upgrade_rehearsal.py dropped --kept <restored
     inventory.db> --displaced <the copied inventory.db>`. It lists every ledger entry
     and shipment present only in the displaced set (date-time, type, Part, Lot, quantity,
     Locations, operator, reference, shipment number). Run it **before any new work** is
     posted to the restored inventory: record ids are reused afterwards.
   - Without Python: open the disposable copy with a second copy of the application (launch
     with `--database` pointing at it), export Transactions and Shipments CSV from it and
     from the restored inventory, and compare **complete rows**. Keep duplicate rows (two
     identical receipts are two entries: sort both files and diff them, do not de-duplicate).
     Do not use the backup's file-name time as a cutoff: the ledger stores minutes only, so
     an entry made in the same minute as the backup cannot be told from one made before it;
     if you narrow by time, include the whole minute of the backup.
3. For each receipt, shipment, move or count: confirm it really happened. Re-enter it
   with Receive, Ship, Move or Adjust Count, writing the original reference
   (including an old shipment number) in the reference field. A re-entered shipment
   gets a new `SHP-` number; the old number is only in the reference.
4. Where the physical shelf disagrees with the restored balance and no record is
   needed, use Adjust Count with a reason.
5. Check the dashboard and the affected Parts once more, then take a manual backup
   and [verify it](#verify-a-backup).
6. Keep the aside folder until the work is reconciled and signed off.

Do not edit the database with other tools, and do not copy rows between inventories.

## Evidence

[`tests/test_upgrade_rehearsal.py`](../../tests/test_upgrade_rehearsal.py) holds the
public-API tests on temporary SQLite; `scripts/upgrade_rehearsal.py` drives the real
application. Both use the committed pre-migration fixture
[`premigration-inventory.sql`](../../tests/fixtures/upgrade/premigration-inventory.sql):
8 Parts, 8 Lots, 11 balances, 28 ledger rows (RECEIVE, MOVE_OUT/IN, SHIP, SHIP_BOM,
BOM_CONSUME, COUNT_CORRECTION), 4 shipments (two standard, two nested-BOM, one of them
consuming one component from two Lots), 7 per-Lot component snapshots, BOM definitions
edited after those shipments, an inactive Part, and operator/theme preferences. The
fixture was **written by the original application's own store at the pinned last
known-good commit** with a frozen clock (provenance line in the file; a test regenerates
it from that commit and compares the whole text). It is a database written by an older
version of the code, not a synthetic claim. When the fixture was moved to it, its text
below the provenance lines was byte-identical to the one the current store had written
for the same scenario (a one-time comparison, not a standing test); a test does keep the
schema identical to today's. It is still a scripted scenario run through
that release's code, not a copy of an operator's historical database; no such database
is in the repository.

```bash
# Packaged (after `package_bundle.py build`); Linux shown. The workdir must be empty.
xvfb-run -a -s "-screen 0 1920x1080x24" \
  python scripts/upgrade_rehearsal.py rehearse --bundle /tmp/invsys-installed/invsys-desktop \
  --workdir /tmp/invsys-upgrade-rehearsal --evidence /tmp/invsys-upgrade-evidence.json --isolate-network
# Source launch
python scripts/upgrade_rehearsal.py rehearse --source --workdir /tmp/invsys-upgrade-rehearsal \
  --evidence /tmp/invsys-upgrade-evidence.json
```

`--evidence` must name a file that does not exist and lies outside the workdir; the tool
refuses an existing path (a database included, also through a symlink) before launching
anything and creates the file exclusively, so a mistyped path can never overwrite data.

Each rehearsal unpacks the last known-good release into the empty workdir and installs
the fixture as its inventory (`last-known-good/data/inventory.db`; never operational data;
`INVSYS_HOME` points at a directory that must stay absent), then:

1. **Upgrade:** the application's native smoke runs against the copy. Its startup
   backup must equal the pre-upgrade copy; every pre-existing row (ledger, balances,
   shipments, component snapshots, BOM, Lots) must be unchanged afterwards, except the
   two preferences the smoke sets; the schema must be unchanged; ledger and balances
   must reconcile; the manual and startup backups must be in the selected inventory's
   folder and hold only its records.
2. **Restart:** a second launch; its startup backup must equal the first launch's result.
3. **Roll back to the last known-good release:** the original application is started on
   the upgraded inventory and works on it ([above](#last-known-good-release-rehearsed)).
4. **Roll forward:** a launch of the replacement on what the older release left; its
   startup backup must equal that state and every fixture record must still be intact.
5. **Restore:** the first launch's startup backup is restored over the later inventory
   by the closed-app procedure; the result must equal the pre-upgrade inventory, the
   displaced file must equal the pre-restore state, and the ledger entries and
   shipments the restore removed (the replacement's and the older release's) are listed
   in the record.
6. **Reopen:** a launch must open the restored inventory (startup backup equal
   to it) and leave every pre-upgrade record intact.
7. The restore failure table above is exercised and recorded for the platform.

Retained results and what they do and do not establish are in
[packaging.md](packaging.md#recorded-copied-data-upgrade-and-restore-evidence).
