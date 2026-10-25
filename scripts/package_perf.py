#!/usr/bin/env python3
"""Measure the packaged frontend against the approved performance envelope (ticket #55).

    python scripts/package_perf.py run --bundle dist/invsys-desktop \
        --workdir /tmp/invsys-perf --evidence perf-evidence.json

Builds the frozen large acceptance fixture (10,000 Parts, 100,000 transactions, a
1,000-node expanded BOM) unless ``--fixture`` names an existing one, then launches the
*bundle* itself:

* ``1 + 5`` cold launches, each in a new process on a pristine copy of the fixture;
  the time from spawning the process to the dashboard being rendered, correct and
  usable (the probe prints a marker line, the runner times it on its own clock);
* one workflow launch in which the bundle's native probe runs scenarios P01-P04 with
  one warm-up and five measured repeats per step (``inventory_control.desktop_perf``).

Every raw timing, the min/median/max of the measured repeats, the machine, bundle and
fixture records are written to the evidence file. The limits are not options: the exit
status is non-zero if any measured repeat exceeds its target, any correctness assertion
fails, or any step has too few repeats (missing evidence is never a pass).
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import package_bundle  # noqa: E402  # sibling script, resolved through the path set above

from inventory_control import perf  # noqa: E402  # needs the repository root on sys.path
from inventory_control.desktop_perf import USABLE_MARKER  # noqa: E402

LAUNCH_TIMEOUT_SECONDS = 180
WORKFLOW_TIMEOUT_SECONDS = 1800
FIXTURE_DATABASE = "inventory.db"


class PerfError(Exception):
    """The measurement could not be carried out (as opposed to a slow result)."""


def launch_command(bundle: Path, database: Path, mode: str, output: Path) -> list[str]:
    return [
        str(package_bundle.executable_path(bundle)),
        "--database",
        str(database),
        "--perf-check",
        mode,
        "--perf-output",
        str(output),
    ]


def run_probe(command: list[str], cwd: Path, env: dict[str, str], timeout: float) -> dict[str, Any]:
    """Run one probe process and time it from spawn to the usable marker.

    The marker line is stamped with this process's monotonic clock when it is read, so
    bundle start-up, interpreter and Qt initialisation, window creation and the page's
    own load are all inside the measured interval.
    """
    started = time.monotonic()
    marker_at: list[float] = []
    stdout_lines: list[str] = []
    stderr_text: list[str] = []
    # The command is the bundle under test with fixed probe arguments built above.
    with subprocess.Popen(  # noqa: S603
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as process:

        def read_stdout() -> None:
            for line in process.stdout or ():
                if line.strip() == USABLE_MARKER and not marker_at:
                    marker_at.append(time.monotonic())
                stdout_lines.append(line.rstrip())

        def read_stderr() -> None:
            stderr_text.append(process.stderr.read() if process.stderr else "")

        readers = [threading.Thread(target=read_stdout), threading.Thread(target=read_stderr)]
        for reader in readers:
            reader.start()
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            exit_code = -1
            stderr_text.append(f"Timed out after {timeout:.0f} s.")
        for reader in readers:
            reader.join(timeout=30)
    return {
        "exit_code": exit_code,
        "to_usable_ms": round((marker_at[0] - started) * 1000, 1) if marker_at else None,
        "seconds": round(time.monotonic() - started, 1),
        "stdout": package_bundle.excerpt("\n".join(stdout_lines)),
        "stderr": package_bundle.excerpt("".join(stderr_text)),
    }


def read_result(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"errors": ["the probe wrote no result file"], "samples": {}}
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]  # JSON written by the probe


def fixture_record(database: Path) -> dict[str, Any]:
    with database.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = database.parent / "manifest.json"
    return {
        "database_sha256": digest,
        "size_bytes": database.stat().st_size,
        "manifest": json.loads(manifest.read_text(encoding="utf-8"))
        if manifest.is_file()
        else None,
        "truth": perf.fixture_truth(database),
        "storage": str(database.parent),
    }


def ensure_fixture(fixture: Path | None, workdir: Path) -> Path:
    """The large fixture database: the one named, or a new one built through the public API."""
    if fixture is not None:
        database = fixture if fixture.is_file() else fixture / FIXTURE_DATABASE
        if not database.is_file():
            raise PerfError(f"No fixture database at {database}.")
        return database
    from inventory_control.acceptance import create_fixture

    started = time.monotonic()
    database = create_fixture(workdir / "fixture", large=True)
    print(f"Fixture built in {time.monotonic() - started:.0f} s: {database}", flush=True)
    return database


def pristine_copy(fixture: Path, target: Path) -> Path:
    """A new directory holding only the fixture database, so no run sees another's changes."""
    target.mkdir(parents=True)
    copy = target / FIXTURE_DATABASE
    shutil.copyfile(fixture, copy)
    return copy


def measure_launches(
    bundle: Path, fixture: Path, workdir: Path, env: dict[str, str], count: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """Cold launches in separate processes: the first is the warm-up, the rest are measured."""
    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    for run in range(count):
        directory = workdir / f"launch-{run}"
        database = pristine_copy(fixture, directory)
        output = directory / "launch.json"
        result = run_probe(
            launch_command(bundle, database, "launch", output),
            workdir,
            env,
            LAUNCH_TIMEOUT_SECONDS,
        )
        probe = read_result(output)
        if result["exit_code"] != 0 or result["to_usable_ms"] is None or probe.get("errors"):
            errors.append(
                f"launch run {run}: exit {result['exit_code']}, "
                f"errors {probe.get('errors')}, stderr {result['stderr']}"
            )
            continue
        samples.append(
            {
                "run": run,
                "ms": result["to_usable_ms"],
                "page_ms": probe["usable"]["page_ms"],
                "exit_code": result["exit_code"],
                "seconds": result["seconds"],
                "environment": probe.get("environment"),
            }
        )
        shutil.rmtree(directory, ignore_errors=True)
    return samples, errors


def measure_workflow(
    bundle: Path, fixture: Path, workdir: Path, env: dict[str, str]
) -> tuple[dict[str, list[dict[str, Any]]], list[str], dict[str, Any]]:
    directory = workdir / "workflow"
    database = pristine_copy(fixture, directory)
    output = directory / "workflow.json"
    result = run_probe(
        launch_command(bundle, database, "workflow", output),
        workdir,
        env,
        WORKFLOW_TIMEOUT_SECONDS,
    )
    probe = read_result(output)
    errors = list(probe.get("errors", []))
    if result["exit_code"] != 0:
        errors.append(f"workflow probe exit {result['exit_code']}: {result['stderr']}")
    return probe.get("samples", {}), errors, probe


def build_record(
    *,
    bundle: Path,
    fixture: Path,
    launch_samples: list[dict[str, Any]],
    workflow_samples: dict[str, list[dict[str, Any]]],
    errors: list[str],
    probe: dict[str, Any],
) -> dict[str, Any]:
    """The evidence record: judged steps first, then everything needed to repeat the run."""
    results = perf.evaluate(perf.WORKFLOW_STEPS, workflow_samples) + perf.evaluate(
        perf.LAUNCH_STEPS, {"P05.launch": launch_samples}
    )
    outcome = perf.verdict(results, errors)
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "result": "passed" if outcome["passed"] else "failed",
        "verdict": outcome,
        "targets_ms": {
            "interaction": perf.INTERACTION_MS,
            "graph": perf.GRAPH_MS,
            "launch": perf.LAUNCH_MS,
        },
        "method": {
            "warmups": perf.WARMUPS,
            "measured_repeats": perf.REPEATS,
            "timing": "in-page performance.now() from the action to two painted frames after the "
            "expected, correct state (external_ms adds this runner's polling); launch is "
            "process spawn to the usable marker on the runner's monotonic clock",
            "cache": "warm OS file cache after the warm-up run; no cache dropping",
            "shared_runner_note": "GitHub-hosted runners are shared virtual machines: timings are noisy",
        },
        "machine": package_bundle.machine_record(),
        "bundle": package_bundle.bundle_record(bundle),
        "fixture": fixture_record(fixture),
        "probe_environment": probe.get("environment"),
        "steps": results,
        "errors": errors,
        "snapshots": probe.get("snapshots", {}),
    }


def run(bundle: Path, workdir: Path, evidence: Path, fixture: Path | None) -> bool:
    bundle, workdir, evidence = (path.resolve() for path in (bundle, workdir, evidence))
    if not package_bundle.executable_path(bundle).is_file():
        raise PerfError(f"No bundle executable at {package_bundle.executable_path(bundle)}.")
    if workdir.exists() and any(workdir.iterdir()):
        raise PerfError(f"--workdir {workdir} must be empty: the probes write real data.")
    package_bundle.require_display()
    workdir.mkdir(parents=True, exist_ok=True)
    database = ensure_fixture(fixture.resolve() if fixture else None, workdir)
    # Anything written to a default data location would land here and be noticed.
    env = {**os.environ, "INVSYS_HOME": str(workdir / "unexpected-home")}
    launches, errors = measure_launches(bundle, database, workdir, env, perf.WARMUPS + perf.REPEATS)
    workflow, workflow_errors, probe = measure_workflow(bundle, database, workdir, env)
    errors += workflow_errors
    if (workdir / "unexpected-home").exists():
        errors.append("a run wrote to the default data location")
    record = build_record(
        bundle=bundle,
        fixture=database,
        launch_samples=launches,
        workflow_samples=workflow,
        errors=errors,
        probe=probe,
    )
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(summary(record))
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_file).open("a", encoding="utf-8") as stream:
            stream.write(
                f"### Package performance ({record['machine'].get('os', sys.platform)})\n```\n{summary(record)}\n```\n"
            )
    return bool(record["result"] == "passed")


def summary(record: dict[str, Any]) -> str:
    lines = [f"Performance {record['result']}; evidence has every raw timing."]
    lines.append(f"{'step':16} {'status':8} {'target':>7} {'min':>8} {'median':>8} {'max':>8}")
    for item in record["steps"]:
        lines.append(
            f"{item['id']:16} {item['status']:8} {item['target_ms']:>7} "
            f"{item.get('min_ms', '-'):>8} {item.get('median_ms', '-'):>8} {item.get('max_ms', '-'):>8}"
        )
    lines.extend(f"error: {error}" for error in record["errors"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--bundle", type=Path, default=package_bundle.bundle_path(ROOT / "dist"))
    runner.add_argument("--workdir", type=Path, default=None)
    runner.add_argument("--evidence", type=Path, required=True)
    runner.add_argument("--fixture", type=Path, default=None, help="An existing large fixture")
    args = parser.parse_args(argv)
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="invsys-perf-"))
    try:
        return 0 if run(args.bundle, workdir, args.evidence, args.fixture) else 1
    except (PerfError, package_bundle.PackagingError) as exc:
        print(f"package_perf: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
