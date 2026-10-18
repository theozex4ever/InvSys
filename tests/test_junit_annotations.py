"""The CI step that turns a pytest JUnit report into GitHub error annotations.

``gh run view`` lists annotations under the job summary, so one short line per
failing test is enough to act on without downloading the full log.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "junit_annotations.py"
spec = importlib.util.spec_from_file_location("junit_annotations", SCRIPT)
assert spec is not None
assert spec.loader is not None
junit_annotations = importlib.util.module_from_spec(spec)
sys.modules["junit_annotations"] = junit_annotations
spec.loader.exec_module(junit_annotations)


def report(*testcases: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">'
        + "".join(testcases)
        + "</testsuite></testsuites>"
    )


FAILURE = (
    '<testcase classname="tests.test_p" name="test_fail" file="tests/test_p.py" line="2">'
    '<failure message="AssertionError: nope&#10;assert 1 == 2">def test_fail():\n'
    "&gt;       assert 1 == 2\nE       AssertionError: nope\nE       assert 1 == 2\n\n"
    "tests/test_p.py:4: AssertionError</failure></testcase>"
)


def test_failure_points_at_the_failing_line_with_the_node_id_and_message():
    assert junit_annotations.annotations(report(FAILURE)) == [
        "::error file=tests/test_p.py,line=4::tests/test_p.py::test_fail - AssertionError: nope"
    ]


def test_passed_and_skipped_tests_produce_nothing():
    passed = '<testcase classname="tests.test_p" name="test_ok" file="tests/test_p.py" line="0" />'
    skipped = (
        '<testcase classname="tests.test_p" name="test_skip" file="tests/test_p.py" line="5">'
        '<skipped type="pytest.skip" message="unconditional skip">x</skipped></testcase>'
    )

    assert junit_annotations.annotations(report(passed, skipped)) == []


def test_setup_error_in_a_class_falls_back_to_the_definition_line():
    error = (
        '<testcase classname="tests.test_p.TestK" name="test_err" file="tests/test_p.py" line="5">'
        '<error message="failed on setup with &quot;fixture missing&quot;">'
        "E       fixture 'missing' not found\n\n/abs/tests/test_p.py:6</error></testcase>"
    )

    assert junit_annotations.annotations(report(error)) == [
        (
            "::error file=tests/test_p.py,line=6::tests/test_p.py::TestK::test_err"
            " - failed on setup with \"fixture missing\" | E       fixture 'missing' not found"
        )
    ]


def test_collection_error_names_the_module_and_the_underlying_exception():
    error = (
        '<testcase classname="" name="tests.test_broken" file="tests/test_broken.py">'
        '<error message="collection failure">ImportError while importing test module.\n'
        "E   ModuleNotFoundError: No module named 'gone'</error></testcase>"
    )

    assert junit_annotations.annotations(report(error)) == [
        (
            "::error file=tests/test_broken.py::tests/test_broken.py - collection failure"
            " | E   ModuleNotFoundError: No module named 'gone'"
        )
    ]


def test_workflow_command_metacharacters_are_escaped():
    failure = (
        '<testcase classname="tests.a,b" name="test_x[100%:1]" file="tests/a,b.py" line="0">'
        '<failure message="50% done">tests/a,b.py:1: AssertionError</failure></testcase>'
    )

    assert junit_annotations.annotations(report(failure)) == [
        "::error file=tests/a%2Cb.py,line=1::tests/a,b.py::test_x[100%25:1] - 50%25 done"
    ]


def test_main_prints_annotations_and_never_fails_the_step(tmp_path, capsys):
    path = tmp_path / "junit.xml"
    path.write_text(report(FAILURE), encoding="utf-8")

    assert junit_annotations.main([str(path)]) == 0
    assert capsys.readouterr().out.startswith("::error file=tests/test_p.py,line=4::")


@pytest.mark.parametrize("content", [None, "<not xml"])
def test_main_warns_when_the_report_is_missing_or_unreadable(tmp_path, capsys, content):
    path = tmp_path / "junit.xml"
    if content is not None:
        path.write_text(content, encoding="utf-8")

    assert junit_annotations.main([str(path)]) == 0
    assert capsys.readouterr().out.startswith("::warning::")
