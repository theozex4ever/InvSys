"""Exercise the CI helper against competing runs without contacting GitHub."""

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ci_wait.sh"
BASH = shutil.which("bash")
JQ = shutil.which("jq")
pytestmark = pytest.mark.skipif(BASH is None or JQ is None, reason="Needs Bash and jq")
SHA = "a" * 40
BRANCH = "feature/current"


@pytest.fixture
def run_helper(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    calls = tmp_path / "calls.jsonl"
    mock = tmp_path / "github.py"
    mock.write_text(
        """import json
import os
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
state = Path(os.environ["CI_WAIT_STATE"])
data = json.loads(state.read_text())
with Path(os.environ["CI_WAIT_CALLS"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[:2] == ["workflow", "run"]:
    data["runs"] = data["after_dispatch"]
    state.write_text(json.dumps(data))
elif args[:2] == ["run", "list"]:
    runs = data["runs"]
    for option, field in [("--commit", "headSha"), ("--branch", "headBranch")]:
        if option in args:
            value = args[args.index(option) + 1]
            runs = [run for run in runs if run[field] == value]
    runs = runs[:int(args[args.index("--limit") + 1])]
    query = args[args.index("--jq") + 1]
    result = subprocess.run(
        [os.environ["CI_WAIT_JQ"], "-r", query],
        input=json.dumps(runs), text=True, capture_output=True, check=True,
    )
    print(result.stdout, end="")
elif args[:2] == ["run", "watch"]:
    run = next(run for run in data["runs"] if str(run["databaseId"]) == args[2])
    sys.exit(0 if run["conclusion"] == "success" else 1)
elif args[:2] == ["run", "view"]:
    print("run " + args[2])
else:
    raise AssertionError(args)
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("CI_WAIT_STATE", str(state))
    monkeypatch.setenv("CI_WAIT_CALLS", str(calls))
    monkeypatch.setenv("CI_WAIT_JQ", JQ)
    shell = f"""
git() {{
    case "$*" in
        'rev-parse --abbrev-ref HEAD') echo {shlex.quote(BRANCH)} ;;
        'rev-parse HEAD') echo {SHA} ;;
        'ls-remote origin refs/heads/'*) printf '%s\\t%s\\n' {SHA} refs/heads/{BRANCH} ;;
        *) return 99 ;;
    esac
}}
gh() {{ {shlex.quote(Path(sys.executable).as_posix())} {shlex.quote(mock.as_posix())} "$@"; }}
sleep() {{ :; }}
export -f git gh sleep
bash "$@"
"""

    def invoke(runs, *, after_dispatch=None):
        state.write_text(
            json.dumps({"runs": runs, "after_dispatch": after_dispatch}), encoding="utf-8"
        )
        command = [BASH, "-c", shell, "ci-wait-test", SCRIPT.as_posix()]
        if after_dispatch is not None:
            command.append("--dispatch")
        # Fixed local script and mocks; no shell input comes from GitHub.
        result = subprocess.run(  # noqa: S603
            command, check=False, capture_output=True, text=True, timeout=15
        )
        recorded = [json.loads(line) for line in calls.read_text().splitlines()]
        return result, recorded

    return invoke


def run(run_id, *, branch=BRANCH, event="pull_request", conclusion="success"):
    return {
        "databaseId": run_id,
        "headSha": SHA,
        "headBranch": branch,
        "event": event,
        "conclusion": conclusion,
    }


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_waits_for_current_branch_failure_despite_unrelated_green_runs(run_helper, event):
    result, calls = run_helper(
        [
            run(206, branch="feature/other"),
            run(205, event="schedule"),
            run(204, event="merge_group"),
            run(203, event="workflow_dispatch"),
            run(201, event=event, conclusion="failure"),
        ]
    )

    assert result.returncode == 1, result.stderr
    assert "Waiting for CI run 201" in result.stdout
    assert ["run", "watch", "201", "--exit-status", "--interval", "20"] in calls


def test_refuses_to_use_unrelated_runs_when_current_branch_has_none(run_helper):
    result, calls = run_helper([run(202, branch="main"), run(201, event="schedule")])

    assert result.returncode == 2, result.stderr
    assert "No CI run found" in result.stderr
    assert not any(call[:2] == ["run", "watch"] for call in calls)


def test_dispatch_ignores_other_branches_and_older_manual_runs(run_helper):
    result, calls = run_helper(
        [
            run(500, branch="feature/other", event="workflow_dispatch"),
            run(200, event="workflow_dispatch"),
        ],
        after_dispatch=[
            run(501, branch="feature/other", event="workflow_dispatch"),
            run(201, event="workflow_dispatch"),
            run(200, event="workflow_dispatch"),
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "Waiting for CI run 201" in result.stdout
    assert ["workflow", "run", "ci.yml", "--ref", BRANCH] in calls
