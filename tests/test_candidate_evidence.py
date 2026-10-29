"""Consistency of the retained candidate acceptance evidence (ticket #57).

The records are unmodified CI artifacts. These checks read them as data: they
confirm every platform's package, performance and upgrade record names the same
candidate commit and passed, so a record from another commit cannot be filed
beside them unnoticed. They establish nothing about operator sign-off.
"""

import json
from pathlib import Path

import pytest

CANDIDATE = "ec8bc4f20d0d433e695849090287f23426419833"
PLATFORMS = ("linux", "windows", "macos")
EVIDENCE = (
    Path(__file__).resolve().parents[1] / "docs" / "frontend" / "evidence" / "candidate-ec8bc4f"
)


def load(kind: str, platform: str) -> dict:
    return json.loads((EVIDENCE / f"{kind}-{platform}.json").read_text(encoding="utf-8"))


def source_commit(record: dict) -> str:
    bundle = record.get("bundle") or record["application"]
    return bundle["manifest"]["source"]["commit"]


def test_every_record_exists_for_every_platform() -> None:
    for kind in ("package", "upgrade", "performance"):
        for platform in PLATFORMS:
            assert (EVIDENCE / f"{kind}-{platform}.json").is_file(), (kind, platform)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_records_name_the_candidate_commit_and_a_clean_tree(platform: str) -> None:
    for kind in ("package", "upgrade", "performance"):
        record = load(kind, platform)
        bundle = record.get("bundle") or record["application"]
        assert source_commit(record) == CANDIDATE, (kind, platform)
        assert bundle["manifest"]["source"]["uncommitted_changes"] is False, (kind, platform)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_package_smoke_ran_twice_with_restart_persistence(platform: str) -> None:
    record = load("package", platform)
    assert record["result"] == "passed"
    assert [run["run"] for run in record["runs"]] == [1, 2]
    assert all(run["exit_code"] == 0 and run["passed"] for run in record["runs"])
    first, second = record["runs"]
    assert not first["startup_backup_transactions"]
    assert second["startup_backup_transactions"] > 0
    assert record["restart_persistence"]["passed"] is True
    assert record["no_writes_outside_selected_inventory"]["passed"] is True
    assert record["assets_verified"] == record["bundle"]["manifest"]["assets"]
    assert all(check["passed"] for check in record["failure_checks"])


@pytest.mark.parametrize("platform", PLATFORMS)
def test_upgrade_rehearsal_passed_every_step(platform: str) -> None:
    record = load("upgrade", platform)
    assert record["result"] == "passed"
    assert len(record["steps"]) == 9
    assert all(step["passed"] for step in record["steps"])


@pytest.mark.parametrize("platform", PLATFORMS)
def test_performance_run_has_no_missing_or_failed_step(platform: str) -> None:
    record = load("performance", platform)
    assert record["result"] == "passed"
    assert record["verdict"]["passed"] is True
    assert record["verdict"]["failed_steps"] == []
    assert record["verdict"]["missing_steps"] == []
    assert record["errors"] == []


def test_all_platforms_used_the_same_fixture_and_pinned_release() -> None:
    upgrades = [load("upgrade", platform) for platform in PLATFORMS]
    assert len({u["fixture"]["sha256"] for u in upgrades}) == 1
    assert len({u["fixture"]["snapshot_digest"] for u in upgrades}) == 1
    assert len({u["last_known_good"]["commit"] for u in upgrades}) == 1
