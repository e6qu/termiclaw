#!/usr/bin/env bash
set -euo pipefail

branch=$(git rev-parse --abbrev-ref HEAD)

if [ "$branch" = "main" ]; then
    echo "ERROR: Do not commit directly to main. Create a feature branch." >&2
    exit 1
fi

git fetch origin main --quiet 2>/dev/null || true

if git rev-parse --verify origin/main >/dev/null 2>&1; then
    local_main=$(git rev-parse main 2>/dev/null || echo "none")
    remote_main=$(git rev-parse origin/main 2>/dev/null || echo "none")

    if [ "$local_main" != "none" ] && [ "$remote_main" != "none" ] && [ "$local_main" != "$remote_main" ]; then
        echo "WARNING: local main is out of sync with origin/main. Run: git checkout main && git pull" >&2
    fi

    if ! git merge-base --is-ancestor origin/main HEAD 2>/dev/null; then
        echo "ERROR: Branch is not rebased on origin/main. Run: git rebase origin/main" >&2
        exit 1
    fi
fi
