#!/usr/bin/env bash
# Wait for the CI run of the pushed HEAD and print a compact verdict: one line per
# job plus one annotation per failing test. Exits non-zero when the run fails.
#
#   scripts/ci_wait.sh              # the run a PR push already started
#   scripts/ci_wait.sh --dispatch   # start a run on a branch without a PR
#
# Needs an authenticated gh. See docs/ci.md ("CI as the test runner").
set -euo pipefail

dispatch=false
case "${1:-}" in
  "") ;;
  --dispatch) dispatch=true ;;
  *) echo "usage: $0 [--dispatch]" >&2; exit 2 ;;
esac

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" = HEAD ]; then
  echo "Detached HEAD: check out the branch whose CI run you want." >&2
  exit 2
fi
sha="$(git rev-parse HEAD)"
remote_sha="$(git ls-remote origin "refs/heads/$branch" | cut -f1)"
if [ "$remote_sha" != "$sha" ]; then
  echo "HEAD $sha is not what origin/$branch points at; push first." >&2
  exit 2
fi

# Newest CI run id for this branch and commit, of event $1 (empty: push or PR)
# and newer than id $2.
# Run ids grow monotonically, so $2 excludes runs that existed before a dispatch.
newest_run() {
  local filter='.event == "push" or .event == "pull_request"'
  [ -n "$1" ] && filter=".event == \"$1\""
  gh run list --workflow ci.yml --branch "$branch" --commit "$sha" --limit 20 --json databaseId,event \
    --jq "[.[] | select($filter) | select(.databaseId > $2)][0].databaseId // empty"
}

# Without --dispatch, wait for the push/PR run, never an older manual one.
event="" floor=0
if $dispatch; then
  event=workflow_dispatch
  floor="$(newest_run workflow_dispatch 0)"
  floor="${floor:-0}"
  gh workflow run ci.yml --ref "$branch"
fi

run_id=""
for _ in $(seq 1 30); do
  run_id="$(newest_run "$event" "$floor")"
  [ -n "$run_id" ] && break
  sleep 4
done
if [ -z "$run_id" ]; then
  echo "No CI run found for $sha. Open a PR, or rerun with --dispatch." >&2
  exit 2
fi

echo "Waiting for CI run $run_id ($branch @ ${sha:0:7})..."
status=0
gh run watch "$run_id" --exit-status --interval 20 > /dev/null 2>&1 || status=$?
gh run view "$run_id"
if [ "$status" -ne 0 ]; then
  # The tail of each failed job's log up to its first error, without colour codes
  # (gh prints ESC as a literal "^[") or timestamps. The "CI gate" job (named in
  # ci.yml) only repeats the other jobs' results.
  echo
  echo "LAST LINES OF EACH FAILED JOB"
  # Logs can lag behind the verdict; a missing tail must not hide the hint below.
  { gh run view "$run_id" --log-failed 2> /dev/null || true; } \
    | sed -E -e $'s/\x1b\\[[0-9;]*m//g' -e 's/\^\[\[[0-9;]*m//g' \
    | awk -F'\t' -v keep=15 -v width=300 '
        $1 == "CI gate" { next }
        { sub(/^[0-9TZ:.-]+ /, "", $3) }
        !($1 in count) { order[++jobs] = $1; count[$1] = 0 }
        finished[$1] { next }
        { count[$1]++; line[$1, count[$1]] = substr($3, 1, width) }
        index($3, "##[error]") == 1 { finished[$1] = 1 }
        END {
          for (j = 1; j <= jobs; j++) {
            job = order[j]
            print "== " job
            first = count[job] > keep ? count[job] - keep + 1 : 1
            for (i = first; i <= count[job]; i++) print line[job, i]
          }
        }' || true
  echo "Full log: gh run view $run_id --log-failed"
fi
exit "$status"
