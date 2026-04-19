#!/usr/bin/env bash
# Forbid `shlex.quote(...)` inside the argv list that a
# `subprocess.run([...])` / `subprocess.Popen([...])` call passes to the
# kernel. In list mode there is no shell, so quoting only injects
# literal quote characters into the argv — see BUG-15 / BUG-42.
#
# Heuristic: flag any occurrence of `shlex.quote(` in termiclaw/*.py.
# The subprocess call sites that actually need quoting (shell=True
# pipelines) must explicitly opt in via a `# shlex-quote-ok` comment
# on the same line.
set -u

hits=$(grep -rn "shlex\.quote(" termiclaw/ 2>/dev/null \
    | grep -v "# shlex-quote-ok" \
    || true)

if [ -n "$hits" ]; then
    printf "Forbidden shlex.quote in argv (subprocess list mode — quotes go through to the callee):\n%s\n" "$hits" >&2
    printf "Pass the string verbatim, or add '# shlex-quote-ok' if this really is a shell=True call.\n" >&2
    exit 1
fi
exit 0
