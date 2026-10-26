"""Performance verdict rules and the independent fixture reads (no display required).

The measurements themselves come from the native probe in the packaged bundle; these
cover what must never regress about *judging* them: the approved limits are fixed, a
slow or missing measurement is never a pass, and read-only scenarios can be proven
read-only against SQLite directly.
"""

import json
import shutil
import sqlite3
import subprocess
from contextlib import closing

import pytest

from inventory_control import perf
from inventory_control.acceptance import create_fixture
from inventory_control.store import InventoryStore


def samples(*values):
    return [{"run": index, "ms": value} for index, value in enumerate(values)]


def step(step_id):
    return perf.STEPS_BY_ID[step_id]


def test_approved_limits_are_the_issue_targets():
    # 2 s for search/page/review, 5 s for the graph, 10 s for launch; not configurable.
    assert perf.INTERACTION_MS == 2000
    assert perf.GRAPH_MS == 5000
    assert perf.LAUNCH_MS == 10000
    targets = {item.scenario: set() for item in perf.STEPS}
    for item in perf.STEPS:
        targets[item.scenario].add(item.target_ms)
    assert targets["P01"] == targets["P02"] == targets["P03"] == {2000}
    assert targets["P05"] == {10000}
    # The graph is ready within 5 s; its pan/zoom/fit responses are ordinary interactions.
    assert step("P04.explore").target_ms == 5000
    assert {step(f"P04.{key}").target_ms for key in ("zoom", "pan", "fit", "select")} == {2000}


def test_every_scenario_in_the_baseline_has_steps():
    assert {item.scenario for item in perf.STEPS} == {"P01", "P02", "P03", "P04", "P05"}
    assert len({item.id for item in perf.STEPS}) == len(perf.STEPS)
    assert {item.id for item in perf.LAUNCH_STEPS} == {"P05.launch"}


def test_all_measured_repeats_within_target_pass_and_warmup_is_not_judged():
    result = perf.evaluate_step(step("P01.search"), samples(9000, 100, 200, 300, 400, 1999))
    assert result["status"] == "pass"
    assert result["warmup_ms"] == [9000.0]
    assert result["warmup_over_target"] is True
    assert result["measured_ms"] == [100.0, 200.0, 300.0, 400.0, 1999.0]
    assert (result["min_ms"], result["median_ms"], result["max_ms"]) == (100.0, 300.0, 1999.0)


def test_one_slow_measured_repeat_fails_the_step_and_is_not_averaged_away():
    # The mean (about 0.9 s) is far below 2 s; the single 2.001 s repeat still fails.
    result = perf.evaluate_step(step("P01.search"), samples(100, 50, 50, 50, 50, 2001))
    assert result["status"] == "fail"
    assert result["max_ms"] == 2001.0
    assert "1 of 5" in result["reason"]


def test_exactly_the_limit_passes():
    assert perf.evaluate_step(step("P04.explore"), samples(0, *[5000] * 5))["status"] == "pass"
    assert perf.evaluate_step(step("P05.launch"), samples(0, *[10001] * 5))["status"] == "fail"


def test_too_few_repeats_is_missing_evidence_not_a_pass():
    result = perf.evaluate_step(step("P02.search"), samples(100, 100, 100, 100))
    assert result["status"] == "missing"
    assert "3 of 5" in result["reason"]
    assert perf.evaluate_step(step("P02.search"), [])["status"] == "missing"


def test_a_step_that_never_ran_is_judged_missing():
    results = perf.evaluate(perf.WORKFLOW_STEPS, {"P01.search": samples(1, 1, 1, 1, 1, 1)})
    by_id = {item["id"]: item["status"] for item in results}
    assert by_id["P01.search"] == "pass"
    assert {status for key, status in by_id.items() if key != "P01.search"} == {"missing"}


def test_verdict_requires_every_step_to_pass_and_no_errors():
    passing = perf.evaluate(perf.LAUNCH_STEPS, {"P05.launch": samples(1, 1, 1, 1, 1, 1)})
    assert perf.verdict(passing)["passed"] is True
    assert perf.verdict(passing, ["correctness: wrong row count"])["passed"] is False
    assert perf.verdict([])["passed"] is False  # nothing measured is not a success
    slow = perf.evaluate(perf.LAUNCH_STEPS, {"P05.launch": samples(1, 1, 1, 1, 1, 99999)})
    outcome = perf.verdict(slow)
    assert outcome["passed"] is False
    assert outcome["failed_steps"] == ["P05.launch"]
    missing = perf.verdict(perf.evaluate(perf.LAUNCH_STEPS, {}))
    assert missing["missing_steps"] == ["P05.launch"]


def test_fixture_truth_reads_sqlite_independently_of_the_store(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    truth = perf.fixture_truth(database)
    assert (truth["parts"], truth["active_parts"], truth["inactive_parts"]) == (5, 4, 1)
    assert truth["transactions"] == 15
    assert truth["shipments"] == 2
    assert truth["bom_components"] == 3
    # SHIP_BOM rows record the phantom parent's shipped quantity without moving its
    # balance, so on-hand units exceed the ledger sum by exactly that shipment (2 KIT).
    assert truth["balance_units"] - truth["ledger_units"] == 2
    assert perf.reference_count(database, "ACCEPT-OPENING") == 8
    assert perf.reference_count(database, "NO-SUCH-REFERENCE") == 0


def test_type_and_stock_reads_match_the_workflow_fixture(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    assert perf.type_count(database, "RECEIVE") == 8
    assert perf.type_count(database, "NO_SUCH_TYPE") == 0


def test_fixture_truth_never_creates_a_missing_database(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        perf.fixture_truth(tmp_path / "absent.db")
    assert not (tmp_path / "absent.db").exists()


def test_writes_between_names_every_changed_counter(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    before = perf.fixture_truth(database)
    assert perf.writes_between(before, perf.fixture_truth(database)) == []
    store = InventoryStore(database, seed=False)
    try:
        store.receive("STANDARD", 3, "Stock", "NEW", "Perf test", reference="PERF-TEST")
    finally:
        store.engine.dispose()
    changed = perf.writes_between(before, perf.fixture_truth(database))
    assert "transactions: 15 -> 16" in changed
    assert "balance_rows: 9 -> 10" in changed
    assert "balance_units: 63 -> 66" in changed


def test_the_probe_only_accepts_the_two_documented_modes(tmp_path):
    from inventory_control.desktop_perf import PerfProbe

    database = create_fixture(tmp_path / "fixture")
    PerfProbe("launch", tmp_path / "out.json", database)
    PerfProbe("workflow", tmp_path / "out.json", database)
    with pytest.raises(ValueError, match="launch or workflow"):
        PerfProbe("everything", tmp_path / "out.json", database)


def test_review_checks_compare_the_rendered_review_with_sqlite(tmp_path):
    from inventory_control.desktop_perf import PerfProbe, ProbeError

    database = create_fixture(tmp_path / "fixture")
    probe = PerfProbe("launch", tmp_path / "out.json", database)
    standard = (
        "Location / lot\nStock / A\nReviewed lot impact\nBefore\n10\nShipping\n2\n"
        "Lot remaining after shipment\n8"
    )
    probe._check_review("standard", standard, [])
    # Lot "A" must be the lot named, and the remainder must be the real one.
    with pytest.raises(ProbeError, match="Stock"):
        probe._check_review("standard", standard.replace("Stock / A", "Stock / B"), [])
    with pytest.raises(ProbeError, match="Lot remaining"):
        probe._check_review("standard", standard.replace("shipment\n8", "shipment\n9"), [])

    text = "Ready to ship\nBOM build capacity at this location\n3"
    tables = rendered(probe._plan("kit"))
    probe._check_review("kit", text, tables)
    with pytest.raises(ProbeError, match="capacity"):
        probe._check_review("kit", text.replace("location\n3", "location\n4"), tables)
    with pytest.raises(ProbeError, match="Ready to ship"):
        probe._check_review("kit", "Blocked — component shortage", tables)


def test_a_review_with_requirements_but_no_lot_allocations_is_rejected(tmp_path):
    from inventory_control.desktop_perf import PerfProbe, ProbeError

    probe = PerfProbe("launch", tmp_path / "out.json", create_fixture(tmp_path / "fixture"))
    text = "Ready to ship\nBOM build capacity at this location\n3"
    requirements_only = [rendered(probe._plan("kit"))[0], []]
    with pytest.raises(ProbeError, match="allocation"):
        probe._check_review("kit", text, requirements_only)
    wrong_lot = rendered(probe._plan("kit"))
    wrong_lot[1][0][1] = "A\nStock"
    with pytest.raises(ProbeError, match="allocation row 0"):
        probe._check_review("kit", text, wrong_lot)


def edit(database, sql, *parameters):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(sql, parameters)


def test_the_read_only_guard_sees_in_place_edits_that_keep_every_count(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    before = perf.protected_state(database)
    assert perf.writes_between(before, perf.protected_state(database)) == []
    counts = perf.fixture_truth(database)
    # Overwriting a record's reference changes no count and no quantity: the old guard,
    # which compared only those, could not see it.
    edit(database, "UPDATE inventory_transactions SET reference = 'TAMPERED' WHERE id = 1")
    assert perf.writes_between(counts, perf.fixture_truth(database)) == []
    changed = perf.writes_between(before, perf.protected_state(database))
    assert [item.split(":")[0] for item in changed] == ["inventory_transactions_digest"]


@pytest.mark.parametrize(
    "table,sql",
    [
        ("lots", "UPDATE lots SET lot_number = 'RENAMED' WHERE id = 1"),
        ("parts", "UPDATE parts SET description = 'Renamed' WHERE id = 1"),
        ("shipments", "UPDATE shipments SET recipient = 'Someone else' WHERE id = 1"),
        (
            "shipment_components",
            "UPDATE shipment_components SET quantity = quantity + 1 WHERE id = 1",
        ),
        (
            "bom_components",
            "UPDATE bom_components SET quantity_per = quantity_per + 1 WHERE id = 1",
        ),
        ("locations", "UPDATE locations SET active = 0 WHERE id = 1"),
    ],
)
def test_every_protected_table_is_covered_by_content(tmp_path, table, sql):
    database = create_fixture(tmp_path / "fixture")
    before = perf.protected_state(database)
    edit(database, sql)
    assert f"{table}_digest" in "".join(perf.writes_between(before, perf.protected_state(database)))


def test_offsetting_balance_edits_with_the_same_totals_are_still_a_change(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    before = perf.protected_state(database)
    # Move one unit between two balance rows: the row count and the unit total stay the same.
    edit(
        database,
        "UPDATE inventory_balances SET quantity = quantity + CASE id WHEN 1 THEN -1 ELSE 1 END "
        "WHERE id IN (1, 2)",
    )
    after = perf.protected_state(database)
    assert after["balance_units"] == before["balance_units"]
    assert after["balance_rows"] == before["balance_rows"]
    assert any(
        item.startswith("inventory_balances_digest") for item in perf.writes_between(before, after)
    )


def test_settings_are_not_protected_because_preferences_may_change(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    before = perf.protected_state(database)
    edit(database, "UPDATE settings SET value = 'Someone' WHERE key = 'last_operator'")
    assert perf.writes_between(before, perf.protected_state(database)) == []


def planned(database, root, quantity, location="Stock"):
    return perf.expected_plan(database, root, quantity, location)


def test_expected_plan_agrees_with_the_store_for_nested_shared_leaves(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    plan = planned(database, "KIT", 2)
    # 7 LEAF per KIT (1 direct + 2 x 3 through SUB), all taken from lot B once A is empty.
    assert plan["requirements"] == [("LEAF", 14, 21, 0)]
    assert plan["allocations"] == [("LEAF", "B", "Stock", 14, 21)]
    assert plan["buildable"] == 3
    store = InventoryStore(database, seed=False)
    try:
        review = store.prepare_bom_shipment("KIT", 2, "Stock")
    finally:
        store.engine.dispose()
    assert [
        (r.part_number, r.quantity_required, r.stock_available, r.shortage)
        for r in review.requirements
    ] == plan["requirements"]
    assert [
        (line.part_number, line.lot_number, line.location, line.quantity_allocated, line.lot_stock)
        for line in review.lines
    ] == plan["allocations"]


def test_expected_plan_spreads_across_lots_in_lot_order_and_reports_shortage(tmp_path):
    store = InventoryStore(tmp_path / "inventory.db", seed=False)
    try:
        for number in ("TOP", "PART"):
            store.add_part(number, number)
        store.add_bom_component("TOP", "PART", 3)
        for lot, quantity in (("L2", 5), ("L1", 2), ("L0", 1)):
            store.receive("PART", quantity, "Stock", lot, "Pat")
        store.adjust("PART", "Stock", "L0", 0, "Pat", "Counted out")  # a zero-stock lot is skipped
        database = tmp_path / "inventory.db"
        enough = planned(database, "TOP", 2)  # needs 6 of the 7 on hand
        assert enough["allocations"] == [
            ("PART", "L1", "Stock", 2, 2),
            ("PART", "L2", "Stock", 4, 5),
        ]
        assert enough["requirements"] == [("PART", 6, 7, 0)]
        assert enough["buildable"] == 2
        short = planned(database, "TOP", 3)  # needs 9
        assert short["requirements"] == [("PART", 9, 7, 2)]
        assert short["allocations"] == [
            ("PART", "L1", "Stock", 2, 2),
            ("PART", "L2", "Stock", 5, 5),
        ]
        review = store.prepare_bom_shipment("TOP", 3, "Stock")
        assert [(line.lot_number, line.quantity_allocated) for line in review.lines] == [
            ("L1", 2),
            ("L2", 5),
        ]
    finally:
        store.engine.dispose()


def rendered(plan):
    """What the confirmation dialog shows: [requirements rows, allocation rows] as cell text."""
    return [
        [
            [
                f"{part}\nDescription {part}",
                str(required),
                str(available),
                f"{short} short" if short else "0",
            ]
            for part, required, available, short in plan["requirements"]
        ],
        [
            [part, f"{lot}\n{location}", str(allocated), str(lot_stock)]
            for part, lot, location, allocated, lot_stock in plan["allocations"]
        ],
    ]


def test_a_rendered_plan_is_accepted_only_when_every_row_matches(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    plan = planned(database, "KIT", 2)
    assert perf.plan_differences(plan, rendered(plan)) == []

    missing_allocations = rendered(plan)
    missing_allocations[1] = []
    assert any("allocation" in item for item in perf.plan_differences(plan, missing_allocations))

    wrong_lot = rendered(plan)
    wrong_lot[1][0][1] = "A\nStock"
    assert any("LEAF" in item for item in perf.plan_differences(plan, wrong_lot))

    wrong_quantity = rendered(plan)
    wrong_quantity[1][0][2] = "13"
    assert perf.plan_differences(plan, wrong_quantity)

    wrong_requirement = rendered(plan)
    wrong_requirement[0][0][1] = "15"
    assert any("requirement" in item for item in perf.plan_differences(plan, wrong_requirement))

    assert perf.plan_differences(plan, [rendered(plan)[0]]) == [
        "expected a requirements table and an allocations table, found 1 table(s)"
    ]
    extra = rendered(plan)
    extra[1].append(["LEAF", "Z\nStock", "1", "1"])
    assert perf.plan_differences(plan, extra)


def test_an_empty_plan_for_a_part_without_a_bom_has_no_rows(tmp_path):
    database = create_fixture(tmp_path / "fixture")
    plan = planned(database, "STANDARD", 1)
    assert plan["requirements"] == [("STANDARD", 1, 16, 0)]
    assert plan["allocations"] == [("STANDARD", "A", "Stock", 1, 10)]


NODE = shutil.which("node")
RUNNER = r"""
const fs = require('fs');
globalThis.window = globalThis;
globalThis.document = { visibilityState: 'visible', querySelector: () => null, querySelectorAll: () => [] };
const mode = process.argv[3];
const first = (() => { let calls = 0; return callback => { if (calls++ === 0) setTimeout(callback, 1); }; })();
globalThis.requestAnimationFrame = mode === 'working' ? callback => setTimeout(callback, 1)
  : mode === 'first-frame-only' ? first : () => {};
(0, eval)(fs.readFileSync(process.argv[2], 'utf8'));
const watch = process.argv[4] === 'usable';
if (watch) {
  const heading = { textContent: 'Active parts', querySelector: () => ({ textContent: '9' }) };
  document.querySelectorAll = selector => selector === '#dashboard-data .stat' ? [heading] : [];
  // Make every readiness condition true so only the missing frames can matter.
  window.P = { ...window.P, n: selector => selector.includes('history') ? 50 : 1, text: () => '1 parts', loading: () => false, $: () => ({ disabled: false }), actionable: () => true };
  window.perfWatchUsable(9, 1, 300);
} else {
  window.perfTimed(() => {}, () => true, 300);
}
const started = Date.now();
const poll = () => {
  const done = watch ? (window.perfUsableAt !== null || window.perfUsableError) : window.perfResult;
  if (done || Date.now() - started > 3000) {
    console.log(JSON.stringify({ result: watch ? { at: window.perfUsableAt, error: window.perfUsableError } : JSON.parse(window.perfResult || 'null') }));
  } else setTimeout(poll, 5);
};
poll();
"""


def run_helpers(tmp_path, mode, target="timed"):
    from inventory_control.desktop_perf import HELPERS

    (tmp_path / "helpers.js").write_text(HELPERS, encoding="utf-8")
    (tmp_path / "runner.js").write_text(RUNNER, encoding="utf-8")
    output = subprocess.run(  # noqa: S603  # node with fixed arguments and files this test just wrote
        [NODE, str(tmp_path / "runner.js"), str(tmp_path / "helpers.js"), mode, target],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    return json.loads(output)["result"]


@pytest.mark.skipif(NODE is None, reason="the page helpers are checked with Node")
def test_a_step_with_two_painted_frames_is_a_measurement(tmp_path):
    result = run_helpers(tmp_path, "working")
    assert result["frames"] == 2
    assert "timeout" not in result
    assert result["visibility"] == "visible"


@pytest.mark.skipif(NODE is None, reason="the page helpers are checked with Node")
@pytest.mark.parametrize("mode,frames", [("stalled", 0), ("first-frame-only", 1)])
def test_a_step_without_both_frames_is_a_timeout_never_a_quick_success(tmp_path, mode, frames):
    # The state is reached at once, but the renderer produced fewer than two frames: the old
    # helper reported ~250 ms as a success here.
    result = run_helpers(tmp_path, mode)
    assert result["timeout"] is True
    assert result["frames"] == frames
    assert "animation frames" in result["problem"]
    assert result["ms"] >= 300


@pytest.mark.skipif(NODE is None, reason="the page helpers are checked with Node")
def test_the_launch_marker_also_needs_both_frames(tmp_path):
    painted = run_helpers(tmp_path, "working", "usable")
    assert painted["at"] is not None
    assert not painted["error"]
    stalled = run_helpers(tmp_path, "stalled", "usable")
    assert stalled["at"] is None
    assert "animation frames" in stalled["error"]


class FakeWindow:
    """Answers the probe's page calls with a canned step result."""

    def __init__(self, result):
        self.result = result

    def evaluate_js(self, script):
        return json.dumps(self.result) if script.strip() == "window.perfResult" else None


def timed_with(tmp_path, result):
    from inventory_control.desktop_perf import PerfProbe

    probe = PerfProbe("workflow", tmp_path / "out.json", create_fixture(tmp_path / "fixture"))
    probe._window = FakeWindow({"visibility": "visible", **result})
    return probe, probe._timed("P01.search", "", "true", 0)


def test_the_probe_records_how_many_frames_each_sample_waited_for(tmp_path):
    probe, sample = timed_with(tmp_path, {"ms": 12.0, "ready_ms": 5.0, "frames": 2, "marks": {}})
    assert sample["frames"] == 2
    assert probe.samples["P01.search"] == [sample]


@pytest.mark.parametrize("frames", [0, 1, None])
def test_a_sample_without_two_frames_is_refused_even_if_the_page_called_it_done(tmp_path, frames):
    from inventory_control.desktop_perf import ProbeError

    result = {"ms": 252.9, "ready_ms": 2.0, "marks": {}}
    if frames is not None:
        result["frames"] = frames
    with pytest.raises(ProbeError, match="animation frames"):
        timed_with(tmp_path, result)
