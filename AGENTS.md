# Agent validation workflow

GitHub CI runs the tests, static checks, builds, and native smoke checks.
Local test execution is optional, including affected test files; it is not a
prerequisite for committing, pushing, or completing agent work.

1. Implement the change and add or update relevant tests for CI to execute.
2. Review the diff, commit, and push to the task's branch. A PR push starts CI;
   on a branch without a PR, start it with `scripts/ci_wait.sh --dispatch`.
3. Wait for CI on the latest pushed commit. Use `scripts/ci_wait.sh`, or the
   environment's PR watcher when available.
4. If CI fails, inspect its annotations and failed-job logs, fix the cause,
   push again, and wait for the new result. A cancelled or superseded run is
   not a passing result.
5. Report completion only after **CI gate** and the PR's other required checks
   are green for that commit. Include the CI run link in the final report.

Local checks are available for an explicit user request or optional debugging
of a CI failure. If CI is unavailable, report validation as blocked rather
than treating local results as a green CI result. See `docs/ci.md` for commands
and failure reporting.
