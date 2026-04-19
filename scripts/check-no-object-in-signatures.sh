#!/usr/bin/env bash
# Block `object` or `Any` in type annotations outside boundary modules:
#   - termiclaw/validate.py  (validator combinators — the designated boundary)
#   - termiclaw/planner.py   (internal validators consume dict[str, object])
#   - termiclaw/task_file.py (TOML boundary for task specs)
#   - termiclaw/atif.py      (ATIF export parses arbitrary persisted JSON)
#
# Matches annotation contexts only: `: object`, `-> object`, `: Any`,
# `-> Any`, `[object`, `[Any`, `| object`, `| Any`. Does not match
# `object` / `Any` in docstrings or identifiers.

set -euo pipefail

patterns=': object[,)=]|-> object[,:]|\[object[],]|\| object\b|: Any\b|-> Any\b|\[Any[],]|\| Any\b'

matches=$(grep -rEn "${patterns}" termiclaw/ \
  --exclude-dir=__pycache__ \
  2>/dev/null \
  | grep -v 'termiclaw/validate.py:' \
  | grep -v 'termiclaw/planner.py:' \
  | grep -v 'termiclaw/task_file.py:' \
  | grep -v 'termiclaw/atif.py:' \
  || true)

if [ -n "$matches" ]; then
    echo "ERROR: \`object\`/\`Any\` found in type annotations"
    echo "(allowed only in validate.py, planner.py, task_file.py boundary layer):"
    echo
    echo "$matches"
    exit 1
fi
