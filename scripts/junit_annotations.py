#!/usr/bin/env python3
"""Print one GitHub error annotation per failing test in a pytest JUnit report.

``gh run view`` shows annotations under the job list, so a failed CI run can be
read in a few lines instead of a full log. Expects ``-o junit_family=xunit1`` so
each test case carries its file. Always exits 0: the test step owns the verdict.

    python scripts/junit_annotations.py "$RUNNER_TEMP/junit.xml"
"""

import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

MESSAGE_LIMIT = 300


def annotations(report: str) -> list[str]:
    """Return a workflow error command for each failed or errored test case."""
    # pytest wrote this report in the same job; it is not untrusted input.
    root = ET.fromstring(report)  # noqa: S314
    lines = []
    for case in root.iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        file = case.get("file", "")
        text = problem.text or ""
        properties = f"file={_escape_property(file)}" if file else ""
        line = _failing_line(file, text, case.get("line"))
        if line is not None:
            properties += f",line={line}"
        message = f"{_node_id(case, file)} - {_summary(problem.get('message', ''), text)}"
        lines.append(f"::error {properties}::{_escape_data(message)}")
    return lines


def _node_id(case: ET.Element, file: str) -> str:
    """Rebuild pytest's node id: file, then any class names, then the test name."""
    classname = case.get("classname", "")
    name = case.get("name", "")
    if not classname:
        # Collection errors name the module itself.
        return file or name
    module = file.removesuffix(".py").replace("/", ".")
    classes = classname.removeprefix(module).lstrip(".")
    return "::".join(part for part in (file or classname, *classes.split("."), name) if part)


def _failing_line(file: str, text: str, definition: str | None) -> int | None:
    """Prefer the last traceback frame in the test file; fall back to the definition."""
    if file:
        frames = re.findall(rf"(?:^|/){re.escape(file)}:(\d+)", text, re.MULTILINE)
        if frames:
            return int(frames[-1])
    if definition is not None and definition.isdigit():
        # xunit1 reports the zero-based line of the ``def``.
        return int(definition) + 1
    return None


def _summary(message: str, text: str) -> str:
    """First line of pytest's message, plus the last ``E`` line when it adds detail."""
    first = message.strip().splitlines()[0] if message.strip() else ""
    explanations = [line.rstrip() for line in text.splitlines() if line.startswith("E ")]
    last = explanations[-1] if explanations else ""
    parts = [first]
    if last and re.sub(r"^E\s+", "", last) not in message:
        parts.append(last)
    summary = " | ".join(part for part in parts if part)
    return summary[:MESSAGE_LIMIT]


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def main(argv: list[str]) -> int:
    path = Path(argv[0])
    try:
        found = annotations(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        print(f"::warning::No readable JUnit report at {path}: {exc}")
        return 0
    for line in found:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
