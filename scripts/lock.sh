#!/usr/bin/env bash
# Regenerate the hash-pinned Python lock files from their range manifests.
#
#   scripts/lock.sh             keep existing pins that still satisfy the ranges
#   scripts/lock.sh --upgrade   move every pin to the newest allowed version
#   scripts/lock.sh --upgrade-package pytest   bump one package
#
# CI runs this script with no arguments and fails if the lock files change, so
# a manifest edit without a lock refresh (or a hand-edited lock) cannot merge.
# Locks are universal: one file covers Linux, Windows and macOS on Python 3.12+.
set -euo pipefail
cd "$(dirname "$0")/.."

common=(
  --universal
  --python-version 3.12
  --generate-hashes
  --quiet
  --custom-compile-command "scripts/lock.sh"
)
uv pip compile requirements-dev.txt "${common[@]}" "$@" -o requirements.lock.txt
uv pip compile requirements-ci.txt "${common[@]}" "$@" -o requirements-ci.lock.txt
