"""Performance verdict rules and the independent fixture reads (no display required).

The measurements themselves come from the native probe in the packaged bundle; these
cover what must never regress about *judging* them: the approved limits are fixed, a
slow or missing measurement is never a pass, and read-only scenarios can be proven
read-only against SQLite directly.
"""

import sqlite3

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
    # LEAF holds A=0 and B=21 in Stock after the baseline shipment, so 21 in all; a Part
    # with no balance there counts as nothing, and the smallest of several wins.
    assert perf.smallest_stock(database, ["LEAF"], "Stock") == 21
    assert perf.smallest_stock(database, ["LEAF", "SUB"], "Stock") == 10
    assert perf.smallest_stock(database, ["LEAF", "INACTIVE"], "Receiving") == 0


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


def test_review_content_checks_compare_with_stock_read_from_sqlite(tmp_path):
    from inventory_control.desktop_perf import PerfProbe, ProbeError

    database = create_fixture(tmp_path / "fixture")
    probe = PerfProbe("launch", tmp_path / "out.json", database)
    standard = "Location / lot\nStock / A\nReviewed lot impact\nBefore\n10\nShipping\n2\nLot remaining after shipment\n8"
    probe._check_review("standard", standard)
    # Lot "A" must be the lot named, and the remainder must be the real one.
    with pytest.raises(ProbeError, match="Stock"):
        probe._check_review("standard", standard.replace("Stock / A", "Stock / B"))
    with pytest.raises(ProbeError, match="Lot remaining"):
        probe._check_review("standard", standard.replace("shipment\n8", "shipment\n9"))
    kit = (
        "Ready to ship\nBOM build capacity at this location\n3\nLEAF\tAcceptance LEAF\t14\t21\t0\n"
        "LEAF\tB\nStock\t14\t21"
    )
    probe._check_review("kit", kit)
    with pytest.raises(ProbeError, match="capacity"):
        probe._check_review("kit", kit.replace("location\n3", "location\n4"))
    with pytest.raises(ProbeError, match="Ready to ship"):
        probe._check_review("kit", kit.replace("Ready to ship", "Blocked — component shortage"))
