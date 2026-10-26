"""Performance envelope for the packaged frontend: targets, verdict rules, independent truth.

The approved limits (ticket #39/#55) are fixed here and are never parameters of a
run: common search, page and review interactions 2 s, the expanded-BOM graph 5 s,
packaged launch to a usable dashboard 10 s. The probe that measures them
(``desktop_perf``) and the runner that launches the bundle (``scripts/package_perf.py``)
share these definitions, so a missing measurement can never read as a pass.
"""

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, TypedDict

# One warm-up then five measured repeats per step, and the same for cold launches.
WARMUPS = 1
REPEATS = 5

INTERACTION_MS = 2000
GRAPH_MS = 5000
LAUNCH_MS = 10000


@dataclass(frozen=True)
class Step:
    """One user-visible interaction: from the operator's action to a usable, painted result."""

    scenario: str
    key: str
    label: str
    target_ms: int

    @property
    def id(self) -> str:
        return f"{self.scenario}.{self.key}"


STEPS: tuple[Step, ...] = (
    Step("P01", "search", "Search PERF-00999", INTERACTION_MS),
    Step("P01", "open_part", "Open the Part drawer", INTERACTION_MS),
    Step("P01", "clear", "Clear the search", INTERACTION_MS),
    Step("P01", "inactive", "Filter inactive Parts", INTERACTION_MS),
    Step("P01", "active", "Filter active Parts", INTERACTION_MS),
    Step("P01", "low_stock", "Filter Low stock", INTERACTION_MS),
    Step("P01", "clear_filters", "Clear filters", INTERACTION_MS),
    Step("P01", "sort", "Sort by Stock, descending", INTERACTION_MS),
    Step("P01", "next_page", "Next 100-row catalog page", INTERACTION_MS),
    Step("P02", "open", "Open History", INTERACTION_MS),
    Step("P02", "search", "Search PERF-RECEIPT-050000", INTERACTION_MS),
    Step("P02", "open_record", "Open the exact History record", INTERACTION_MS),
    Step("P02", "clear", "Clear History filters", INTERACTION_MS),
    Step("P02", "next_page", "Next 50-row page", INTERACTION_MS),
    Step("P02", "type_filter", "Filter by transaction type", INTERACTION_MS),
    Step("P03", "open_ship", "Open Ship", INTERACTION_MS),
    Step("P03", "select_standard", "Select STANDARD for review", INTERACTION_MS),
    Step("P03", "review_standard", "Review STANDARD lot A, quantity 2", INTERACTION_MS),
    Step("P03", "select_kit", "Select KIT for review", INTERACTION_MS),
    Step("P03", "review_kit", "Review KIT BOM shipment, quantity 2", INTERACTION_MS),
    Step("P03", "select_root", "Select PERF-ROOT for review", INTERACTION_MS),
    Step("P03", "review_root", "Review PERF-ROOT BOM shipment, quantity 1", INTERACTION_MS),
    Step("P04", "explore", "PERF-ROOT explorer: 1,000 nodes laid out and usable", GRAPH_MS),
    Step("P04", "zoom", "Zoom the 1,000-node graph", INTERACTION_MS),
    Step("P04", "pan", "Pan the 1,000-node graph", INTERACTION_MS),
    Step("P04", "fit", "Fit the 1,000-node graph", INTERACTION_MS),
    Step("P04", "select", "Select a node in the 1,000-node graph", INTERACTION_MS),
    Step("P04", "labels", "Zoom to 100% so every node's text is laid out", INTERACTION_MS),
    Step("P05", "launch", "Launch to a usable dashboard", LAUNCH_MS),
)
STEPS_BY_ID = {step.id: step for step in STEPS}
LAUNCH_STEPS = tuple(step for step in STEPS if step.scenario == "P05")
WORKFLOW_STEPS = tuple(step for step in STEPS if step.scenario != "P05")


def summarize(measured_ms: Sequence[float]) -> dict[str, float]:
    """Min, median and max of the measured repeats; every raw value is kept elsewhere."""
    if not measured_ms:
        return {}
    return {
        "min_ms": round(min(measured_ms), 1),
        "median_ms": round(median(measured_ms), 1),
        "max_ms": round(max(measured_ms), 1),
    }


def evaluate_step(step: Step, samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Judge one step. Each measured repeat must meet the target; too few repeats is *missing*.

    ``samples`` are in run order; the first ``WARMUPS`` are warm-ups: recorded in full but
    not judged. A warm-up that exceeds the target is still reported, never hidden.
    """
    warmups = [float(sample["ms"]) for sample in samples[:WARMUPS]]
    measured = [float(sample["ms"]) for sample in samples[WARMUPS:]]
    slow = [value for value in measured if value > step.target_ms]
    if len(measured) < REPEATS:
        status = "missing"
        reason = f"{len(measured)} of {REPEATS} measured repeats completed"
    elif slow:
        status = "fail"
        reason = f"{len(slow)} of {len(measured)} measured repeats exceeded {step.target_ms} ms"
    else:
        status = "pass"
        reason = ""
    return {
        "id": step.id,
        "scenario": step.scenario,
        "label": step.label,
        "target_ms": step.target_ms,
        "status": status,
        "reason": reason,
        "warmup_ms": [round(value, 1) for value in warmups],
        "warmup_over_target": any(value > step.target_ms for value in warmups),
        "measured_ms": [round(value, 1) for value in measured],
        **summarize(measured),
        "samples": list(samples),
    }


def evaluate(
    steps: Sequence[Step], samples_by_step: Mapping[str, Sequence[Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    """Every required step is judged; a step with no samples is *missing*, not passing."""
    return [evaluate_step(step, samples_by_step.get(step.id, ())) for step in steps]


def verdict(results: Sequence[Mapping[str, Any]], errors: Sequence[str] = ()) -> dict[str, Any]:
    """Overall result: pass only if every step passed and nothing else went wrong."""
    failed = [item["id"] for item in results if item["status"] == "fail"]
    missing = [item["id"] for item in results if item["status"] == "missing"]
    return {
        "passed": not failed and not missing and not errors and bool(results),
        "failed_steps": failed,
        "missing_steps": missing,
        "errors": list(errors),
    }


def fixture_truth(database: Path) -> dict[str, int]:
    """Counts read straight from SQLite (not through the store), read-only and immutable-safe.

    Used to check what the UI rendered against an independent source, and to prove that
    read-only scenarios (searches, reviews) wrote nothing.
    """
    queries = {
        "parts": "SELECT COUNT(*) FROM parts",
        "active_parts": "SELECT COUNT(*) FROM parts WHERE active = 1",
        "inactive_parts": "SELECT COUNT(*) FROM parts WHERE active = 0",
        "transactions": "SELECT COUNT(*) FROM inventory_transactions",
        "shipments": "SELECT COUNT(*) FROM shipments",
        "bom_components": "SELECT COUNT(*) FROM bom_components",
        "balance_rows": "SELECT COUNT(*) FROM inventory_balances",
        "balance_units": "SELECT COALESCE(SUM(quantity), 0) FROM inventory_balances",
        "ledger_units": "SELECT COALESCE(SUM(quantity_change), 0) FROM inventory_transactions",
    }
    # mode=ro never creates the file; no journal is touched by plain reads.
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        return {
            name: int(connection.execute(sql).fetchone()[0])  # constant statements above
            for name, sql in queries.items()
        }


def reference_count(database: Path, reference: str) -> int:
    """How many ledger rows carry exactly this reference (independent of the History search)."""
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM inventory_transactions WHERE reference = ?", (reference,)
        ).fetchone()
    return int(row[0])


def type_count(database: Path, tx_type: str) -> int:
    """How many ledger rows have exactly this transaction type."""
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM inventory_transactions WHERE tx_type = ?", (tx_type,)
        ).fetchone()
    return int(row[0])


# Everything an operator's traceability rests on. Settings are left out on purpose: the
# operator name and theme are preferences that a session may legitimately change.
PROTECTED_TABLES = (
    "parts",
    "locations",
    "lots",
    "inventory_balances",
    "inventory_transactions",
    "shipments",
    "shipment_components",
    "bom_components",
)


def protected_digests(database: Path) -> dict[str, str]:
    """A row count and a SHA-256 of the full content of every protected table.

    Counts and sums cannot see an overwritten reference, a re-assigned Lot or two balances
    that offset each other; hashing every column of every row can.
    """
    digests: dict[str, str] = {}
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        for table in PROTECTED_TABLES:
            digest = hashlib.sha256()
            rows = 0
            # The table names are the constants above, never input.
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid"):  # noqa: S608
                digest.update(repr(row).encode())
                rows += 1
            digests[f"{table}_digest"] = f"{rows} rows, sha256 {digest.hexdigest()}"
    return digests


def protected_state(database: Path) -> dict[str, int | str]:
    """Counts, sums and full-content digests: what a read-only scenario must leave unchanged."""
    return {**fixture_truth(database), **protected_digests(database)}


class ExpectedPlan(TypedDict):
    """A BOM shipment review derived from the BOM rows and balances alone."""

    requirements: list[tuple[str, int, int, int]]  # part, required, available, shortage
    allocations: list[tuple[str, str, str, int, int]]  # part, lot, location, consume, lot stock
    buildable: int


def expected_plan(database: Path, root: str, quantity: int, location: str) -> ExpectedPlan:
    """What the review of shipping ``quantity`` of ``root`` from ``location`` must show.

    Deliberately a second, simple implementation read straight from SQLite: Leaf materials
    aggregated over every path, stock summed over a Part's Lots at the Location, and the
    positive-stock Lots consumed in Lot-number order. A Part without a BOM is its own Leaf.
    """
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        children: dict[str, list[tuple[str, int]]] = {}
        for parent, child, per in connection.execute(
            "SELECT p.part_number, c.part_number, b.quantity_per FROM bom_components b "
            "JOIN parts p ON p.id = b.parent_part_id JOIN parts c ON c.id = b.component_part_id"
        ):
            children.setdefault(parent, []).append((child, per))
        required: dict[str, int] = {}
        pending = [(root, quantity)]
        while pending:
            part, need = pending.pop()
            if part in children:
                pending.extend((child, need * per) for child, per in children[part])
            else:
                required[part] = required.get(part, 0) + need
        lots: dict[str, list[tuple[str, int]]] = {part: [] for part in required}
        for part, lot, units in connection.execute(
            "SELECT p.part_number, l.lot_number, b.quantity FROM inventory_balances b "
            "JOIN parts p ON p.id = b.part_id JOIN lots l ON l.id = b.lot_id "
            "JOIN locations loc ON loc.id = b.location_id WHERE loc.name = ? "
            "ORDER BY p.part_number, l.lot_number",
            (location,),
        ):
            if part in lots:
                lots[part].append((lot, int(units)))
    requirements: list[tuple[str, int, int, int]] = []
    allocations: list[tuple[str, str, str, int, int]] = []
    buildable = None
    for part in sorted(required):
        available = sum(units for _, units in lots[part])
        requirements.append((part, required[part], available, max(required[part] - available, 0)))
        per_build = required[part] // quantity
        buildable = (
            min(buildable, available // per_build)
            if buildable is not None
            else available // per_build
        )
        remaining = required[part]
        for lot, units in lots[part]:
            if units > 0 and remaining > 0:
                taken = min(remaining, units)
                allocations.append((part, lot, location, taken, units))
                remaining -= taken
    return {"requirements": requirements, "allocations": allocations, "buildable": buildable or 0}


def plan_differences(plan: ExpectedPlan, tables: Sequence[Sequence[Sequence[str]]]) -> list[str]:
    """Every way the rendered review tables differ from the expected plan (empty = identical).

    ``tables`` is the cell text of the dialog's two tables: requirements, then allocations.
    Row order matters (Part, then Lot number), and extra or missing rows are differences.
    """
    if len(tables) != 2:
        return [
            f"expected a requirements table and an allocations table, found {len(tables)} table(s)"
        ]
    differences: list[str] = []
    wanted_requirements = [
        [part, str(required), str(available), f"{short} short" if short else "0"]
        for part, required, available, short in plan["requirements"]
    ]
    shown_requirements = [[row[0].split("\n")[0], *row[1:]] for row in tables[0] if len(row) == 4]
    if len(tables[0]) != len(shown_requirements):
        differences.append("a requirement row did not have four cells")
    differences += _row_differences("requirement", wanted_requirements, shown_requirements)
    wanted_allocations = [
        [part, f"{lot}\n{location}", str(taken), str(units)]
        for part, lot, location, taken, units in plan["allocations"]
    ]
    shown_allocations = [list(row) for row in tables[1]]
    return differences + _row_differences("allocation", wanted_allocations, shown_allocations)


def _row_differences(kind: str, wanted: list[list[str]], shown: list[list[str]]) -> list[str]:
    if len(wanted) != len(shown):
        return [f"expected {len(wanted)} {kind} rows, found {len(shown)}"]
    return [
        f"{kind} row {index}: expected {want}, found {have}"
        for index, (want, have) in enumerate(zip(wanted, shown, strict=True))
        if want != have
    ][:5]


def writes_between(before: Mapping[str, int | str], after: Mapping[str, int | str]) -> list[str]:
    """Every counter, sum or content digest that changed; read-only scenarios give an empty list."""
    return [
        f"{name}: {before[name]} -> {after[name]}"
        for name in before
        if before[name] != after.get(name)
    ]
