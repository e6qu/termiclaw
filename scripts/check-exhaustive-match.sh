#!/usr/bin/env bash
# Forbid `case _:` (default arm) in `termiclaw/decide.py` and
# `termiclaw/shell.py`. The whole point of the match statements there
# is exhaustive dispatch over the `Event` and `Command` unions — a
# default arm silently swallows new variants.

set -euo pipefail

matches=$(grep -En '^\s*case\s+_\s*:' \
  termiclaw/decide.py \
  termiclaw/shell.py \
  2>/dev/null || true)

if [ -n "$matches" ]; then
    echo "ERROR: found 'case _:' in exhaustive-match core:"
    echo
    echo "$matches"
    echo
    echo "Remove the default arm and add explicit branches for every variant."
    exit 1
fi
