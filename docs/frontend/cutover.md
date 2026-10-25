# Cutover, restore and rollback

How an existing inventory moves to the replacement desktop packages, how it is
restored from a backup, and how to go back. Parent spec: #39; this is ticket #56.
Everything here is a **closed-application procedure done by an operator** on files.
The application has no restore feature, no database picker and never moves data: the
database is whatever `--database` names (source launches without it keep
`data/inventory.db` under the checkout or `INVSYS_HOME`).

Nothing in the replacement changes the database schema. The pre-migration fixture's
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
  SHA-256 in the cutover log.
- **Startup backup** (`inventory-YYYYMMDD-HHMMSS-startup.db`): taken at every launch
  *before* the database is opened, so it is the inventory exactly as the previous
  session left it. **Manual backup** (`...-manual.db`): taken from Settings, verified
  after writing. Only the newest 20 files are kept.

## Cutover

Do this with the operational inventory only after the bundle for your platform has
passed its package smoke and the upgrade rehearsal (see [evidence](#evidence)).

1. **Close every InvSys program**, including the original PySide6 application. Check
   the task manager/activity monitor: a program still running holds the database.
2. **Take and verify a backup.** Open the *current* (old) release, Settings > Create
   backup. It is reopened and integrity-checked; the page shows its name and size.
   Close the program again. Also copy `inventory.db` to storage outside the data
   folder using the file manager. Note the date, the file size and the Parts count the
   dashboard showed.
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
     the startup backup of this launch is listed (its size equals the file copied in
     step 2).
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
| the displaced files cannot be put back either | the message names the aside folder holding them; copy them back by hand |

Operators doing this by hand: if a step fails, stop, and put anything already moved
back before trying again. An inventory file with a leftover `.restoring` or without
its `-wal` partner is a sign of an interrupted attempt.

## Rollback

There are two different things to go back to; choose by what is wrong.

**The new application misbehaves, the data is fine** (nothing was written, or what
was written is correct). Close the new application and start the last known-good
artifact with the same `--database` (original application: `INVSYS_HOME` set to the
folder that contains `data/inventory.db`, or the same file at the default location).
No data step is needed because the schema is unchanged. Take a backup first.
Whatever the new application recorded stays in the ledger and, the schema being the
same, should be readable by the old release; opening the upgraded inventory with an
older packaged release has not been rehearsed (none exists yet).

**The data is wrong** (an import, a mistaken operation, a damaged file). Restore a
backup as above. This is a data rollback and always needs reconciliation.

An older backup must **never** be placed over later ledger activity without that
reconciliation: the displaced database is the only record of the work done since.

## Reconcile ledger entries after restoring an older backup

Goal: every real-world stock change since the backup ends up recorded again, each
through a normal workflow (so each gets its ledger row), or is knowingly dropped.

1. List what the restore removed: the pre-restore Transactions and Shipments CSVs,
   or open the displaced database in a **second copy** of the application (copy the
   aside file to a disposable folder and launch with `--database` pointing at the
   copy; never open the aside file itself). Entries newer than the backup's time
   (the backup file name carries it) are the candidates.
2. For each receipt, shipment, move or count: confirm it really happened. Re-enter it
   with Receive, Ship, Move or Adjust Count, writing the original reference
   (including an old shipment number) in the reference field. A re-entered shipment
   gets a new `SHP-` number; the old number is only in the reference.
3. Where the physical shelf disagrees with the restored balance and no record is
   needed, use Adjust Count with a reason.
4. Check the dashboard and the affected Parts once more, then take a manual backup.
5. Keep the aside folder until the work is reconciled and signed off.

Do not edit the database with other tools, and do not copy rows between inventories.

## Evidence

[`tests/test_upgrade_rehearsal.py`](../../tests/test_upgrade_rehearsal.py) holds the
public-API tests on temporary SQLite; `scripts/upgrade_rehearsal.py` drives the real
application. Both use the committed pre-migration fixture
[`premigration-inventory.sql`](../../tests/fixtures/upgrade/premigration-inventory.sql):
8 Parts, 8 Lots, 11 balances, 28 ledger rows (RECEIVE, MOVE_OUT/IN, SHIP, SHIP_BOM,
BOM_CONSUME, COUNT_CORRECTION), 4 shipments (two standard, two nested-BOM, one of them
consuming one component from two Lots), 7 per-Lot component snapshots, BOM definitions
edited after those shipments, an inactive Part, and operator/theme preferences.

```bash
# Packaged (after `package_bundle.py build`); Linux shown. The workdir must be empty.
xvfb-run -a -s "-screen 0 1920x1080x24" \
  python scripts/upgrade_rehearsal.py rehearse --bundle /tmp/invsys-installed/invsys-desktop \
  --workdir /tmp/invsys-upgrade-rehearsal --evidence /tmp/invsys-upgrade-evidence.json --isolate-network
# Source launch
python scripts/upgrade_rehearsal.py rehearse --source --workdir /tmp/invsys-upgrade-rehearsal \
  --evidence /tmp/invsys-upgrade-evidence.json
```

Each rehearsal installs the fixture into the empty workdir (never operational data;
`INVSYS_HOME` points at a directory that must stay absent), then:

1. **Upgrade:** the application's native smoke runs against the copy. Its startup
   backup must equal the pre-upgrade copy; every pre-existing row (ledger, balances,
   shipments, component snapshots, BOM, Lots) must be unchanged afterwards, except the
   two preferences the smoke sets; the schema must be unchanged; ledger and balances
   must reconcile; the manual and startup backups must be in the selected inventory's
   folder and hold only its records.
2. **Restart:** a second launch; its startup backup must equal the first launch's result.
3. **Restore:** the first launch's startup backup is restored over the later inventory
   by the closed-app procedure; the result must equal the pre-upgrade inventory, the
   displaced file must equal the pre-restore state, and the ledger entries and
   shipments the restore removed are listed in the record.
4. **Reopen:** a third launch must open the restored inventory (startup backup equal
   to it) and leave every pre-upgrade record intact.
5. The restore failure table above is exercised and recorded for the platform.

Retained results and what they do and do not establish are in
[packaging.md](packaging.md#recorded-copied-data-upgrade-and-restore-evidence).
