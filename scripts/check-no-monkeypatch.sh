#!/usr/bin/env bash
# Forbid pytest's `monkeypatch` fixture anywhere in the codebase — tests
# included. Monkeypatching hides real dependencies and makes refactors
# fragile; if code is hard to test without it, the production code
# should accept an injection seam (env var, argv, constructor param).

set -euo pipefail

matches=$(grep -rEn '\bmonkeypatch\b' termiclaw/ tests/ \
  --include='*.py' \
  --include='*.sh' \
  --exclude-dir=__pycache__ \
  2>/dev/null || true)

if [ -n "$matches" ]; then
    echo "ERROR: 'monkeypatch' found — tests must not stub internals."
    echo "Refactor production code to accept an injection seam instead."
    echo
    echo "$matches"
    exit 1
fi
