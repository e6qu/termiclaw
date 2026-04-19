#!/usr/bin/env bash
# Forbid `# noqa: PLC0415` — ruff's PLC0415 already bans non-top-level
# imports project-wide, but an inline `# noqa` defeats it. Keep all
# imports at module top so dependency shapes are visible at a glance
# and circular-import gotchas surface immediately (instead of hiding
# behind lazy imports).
#
# If there is ever a genuine need for a lazy import (real circular
# dependency that can't be refactored, or a heavy optional dep), add
# an explicit opt-out marker `# lazy-import-ok` instead.
set -u

hits=$(grep -rn --include='*.py' "noqa: *PLC0415" termiclaw/ tests/ 2>/dev/null \
    | grep -v "# lazy-import-ok" \
    || true)

if [ -n "$hits" ]; then
    printf "Forbidden inline imports (PLC0415 noqa is disallowed):\n%s\n" "$hits" >&2
    printf "Move the import to the top of the file. If there really is a circular-import reason, tag with '# lazy-import-ok'.\n" >&2
    exit 1
fi
exit 0
