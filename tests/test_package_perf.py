"""The performance runner: process timing, pristine copies, evidence assembly.

The bundle and the native probe run in the package CI job; these cover the runner's own
decisions with ordinary child processes and a small real fixture.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from inventory_control import perf
from inventory_control.acceptance import create_fixture
from inventory_control.desktop_perf import USABLE_MARKER

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "package_perf.py"
spec = importlib.util.spec_from_file_location("package_perf", SCRIPT)
assert spec is not None
assert spec.loader is not None
package_perf = importlib.util.module_from_spec(spec)
sys.modules["package_perf"] = package_perf
spec.loader.exec_module(package_perf)


def child(code):
    return [sys.executable, "-I", "-c", code]


def test_launch_time_runs_from_spawn_to_the_marker_not_to_exit(tmp_path):
    code = (
        "import sys,time\n"
        "time.sleep(0.4)\n"
        f"print({USABLE_MARKER!r}, flush=True)\n"
        "time.sleep(0.6)\n"
        "print('done')\n"
    )
    result = package_perf.run_probe(child(code), tmp_path, {}, timeout=30)
    assert result["exit_code"] == 0
    assert 400 <= result["to_usable_ms"] < 1000
    assert result["seconds"] >= 1.0
    assert result["stdout"][-1] == "done"


def test_a_run_without_the_marker_has_no_launch_time(tmp_path):
    result = package_perf.run_probe(child("print('started')"), tmp_path, {}, timeout=30)
    assert (result["exit_code"], result["to_usable_ms"]) == (0, None)


def test_only_the_first_marker_counts_and_stderr_is_kept(tmp_path):
    code = (
        f"import sys\nprint({USABLE_MARKER!r}, flush=True)\n"
        f"print({USABLE_MARKER!r}, flush=True)\nsys.stderr.write('warning text')\nsys.exit(3)"
    )
    result = package_perf.run_probe(child(code), tmp_path, {}, timeout=30)
    assert result["exit_code"] == 3
    assert result["stderr"] == ["warning text"]


def test_a_hung_probe_is_killed_and_reported(tmp_path):
    result = package_perf.run_probe(child("import time; time.sleep(60)"), tmp_path, {}, timeout=0.5)
    assert result["exit_code"] == -1
    assert result["to_usable_ms"] is None
    assert "Timed out" in result["stderr"][0]


def test_launch_command_selects_the_database_and_mode(tmp_path):
    command = package_perf.launch_command(
        tmp_path / "invsys-desktop", tmp_path / "x.db", "workflow", tmp_path / "out.json"
    )
    assert command[1:] == [
        "--database",
        str(tmp_path / "x.db"),
        "--perf-check",
        "workflow",
        "--perf-output",
        str(tmp_path / "out.json"),
    ]


def test_each_run_gets_a_pristine_copy_the_fixture_never_changes(tmp_path):
    fixture = create_fixture(tmp_path / "fixture")
    before = package_perf.fixture_record(fixture)
    first = package_perf.pristine_copy(fixture, tmp_path / "run-0")
    first.write_bytes(b"scribbled over by a run")
    second = package_perf.pristine_copy(fixture, tmp_path / "run-1")
    assert second.read_bytes() == fixture.read_bytes()
    assert package_perf.fixture_record(fixture) == before
    with pytest.raises(FileExistsError):
        package_perf.pristine_copy(fixture, tmp_path / "run-1")


def test_fixture_record_identifies_the_data_measured(tmp_path):
    fixture = create_fixture(tmp_path / "fixture")
    record = package_perf.fixture_record(fixture)
    assert len(record["database_sha256"]) == 64
    assert record["manifest"]["profile"] == "workflow"
    assert record["truth"]["parts"] == 5
    assert record["size_bytes"] == fixture.stat().st_size


def test_a_missing_probe_result_is_an_error_not_a_pass(tmp_path):
    result = package_perf.read_result(tmp_path / "absent.json")
    assert result["errors"] == ["the probe wrote no result file"]


def test_ensure_fixture_accepts_a_directory_or_file_and_rejects_nothing_else(tmp_path):
    fixture = create_fixture(tmp_path / "fixture")
    assert package_perf.ensure_fixture(fixture.parent, tmp_path) == fixture
    assert package_perf.ensure_fixture(fixture, tmp_path) == fixture
    with pytest.raises(package_perf.PerfError):
        package_perf.ensure_fixture(tmp_path / "nothing", tmp_path)


def fake_bundle(tmp_path):
    bundle = tmp_path / "invsys-desktop"
    bundle.mkdir()
    executable = package_perf.package_bundle.executable_path(bundle)
    executable.write_bytes(b"binary")
    return bundle


def good_samples(value=100):
    return [{"run": run, "ms": value} for run in range(1 + perf.REPEATS)]


def test_a_complete_fast_run_is_recorded_as_passed(tmp_path):
    fixture = create_fixture(tmp_path / "fixture")
    samples = {step.id: good_samples() for step in perf.WORKFLOW_STEPS}
    record = package_perf.build_record(
        bundle=fake_bundle(tmp_path),
        fixture=fixture,
        launch_samples=good_samples(),
        workflow_samples=samples,
        errors=[],
        probe={"environment": {"user_agent": "QtWebEngine/6"}},
    )
    assert record["result"] == "passed"
    assert {item["scenario"] for item in record["steps"]} == {"P01", "P02", "P03", "P04", "P05"}
    assert record["targets_ms"] == {"interaction": 2000, "graph": 5000, "launch": 10000}
    assert record["fixture"]["manifest"]["profile"] == "workflow"
    assert record["machine"]["logical_cpus"]
    # Round-trips as the JSON that is retained.
    assert json.loads(json.dumps(record))["result"] == "passed"


def test_a_slow_repeat_a_probe_error_or_a_missing_step_fails_the_record(tmp_path):
    fixture = create_fixture(tmp_path / "fixture")
    bundle = fake_bundle(tmp_path)
    samples = {step.id: good_samples() for step in perf.WORKFLOW_STEPS}

    def build(**override):
        arguments = {
            "bundle": bundle,
            "fixture": fixture,
            "launch_samples": good_samples(),
            "workflow_samples": samples,
            "errors": [],
            "probe": {},
        }
        return package_perf.build_record(**{**arguments, **override})

    slow = build(launch_samples=[*good_samples(100), {"run": 9, "ms": 10001}])
    assert slow["result"] == "failed"
    assert slow["verdict"]["failed_steps"] == ["P05.launch"]
    assert build(errors=["P04 run 0: wrong summary"])["result"] == "failed"
    partial = {key: value for key, value in samples.items() if key != "P04.explore"}
    missing = build(workflow_samples=partial)
    assert missing["result"] == "failed"
    assert missing["verdict"]["missing_steps"] == ["P04.explore"]
    assert build(launch_samples=[])["verdict"]["missing_steps"] == ["P05.launch"]


def test_the_summary_lists_every_step_and_error(tmp_path):
    fixture = create_fixture(tmp_path / "fixture")
    record = package_perf.build_record(
        bundle=fake_bundle(tmp_path),
        fixture=fixture,
        launch_samples=good_samples(),
        workflow_samples={},
        errors=["probe: boom"],
        probe={},
    )
    text = package_perf.summary(record)
    assert text.startswith("Performance failed")
    assert "P05.launch" in text
    assert "P04.explore" in text
    assert "error: probe: boom" in text


def test_a_workdir_that_is_not_empty_is_refused(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "old").write_text("x")
    with pytest.raises(package_perf.PerfError, match="must be empty"):
        package_perf.run(fake_bundle(tmp_path), workdir, tmp_path / "e.json", None)


def test_a_missing_bundle_is_refused(tmp_path):
    with pytest.raises(package_perf.PerfError, match="No bundle executable"):
        package_perf.run(tmp_path / "nowhere", tmp_path / "work", tmp_path / "e.json", None)
