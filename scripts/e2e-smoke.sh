#!/usr/bin/env bash
# Manual end-to-end smoke of the termiclaw CLI against real Docker +
# real Claude Code. Not run in CI — exercises the live planner and
# eats Claude quota. Run from the repo root:
#
#   bash scripts/e2e-smoke.sh
#
# Stale containers are cleaned at the start. Output goes to stderr +
# a results table printed at the end.

set -u

# Always invoke termiclaw from the local tree (`uv run`), not whatever
# binary happens to be on PATH — a stale ~/.local/bin/termiclaw will
# silently miss subcommands added since the user's last install.
tc() { uv run -q termiclaw "$@"; }

GREEN=$'\033[0;32m'
RED=$'\033[0;31m'
YELLOW=$'\033[0;33m'
RESET=$'\033[0m'

pass_count=0
fail_count=0
results=()

note() { printf "%s\n" "$*" >&2; }

pass() {
    pass_count=$((pass_count + 1))
    results+=("${GREEN}PASS${RESET} $1")
    note "${GREEN}PASS${RESET} $1"
}

fail() {
    fail_count=$((fail_count + 1))
    results+=("${RED}FAIL${RESET} $1 — $2")
    note "${RED}FAIL${RESET} $1 — $2"
}

skip() {
    results+=("${YELLOW}SKIP${RESET} $1 — $2")
    note "${YELLOW}SKIP${RESET} $1 — $2"
}

run_case() {
    local name="$1"; shift
    local expected_exit="${1:-0}"; shift
    note ""
    note "=== $name ==="
    note "\$ $*"
    local out
    out=$("$@" 2>&1)
    local rc=$?
    if [ "$rc" -eq "$expected_exit" ]; then
        pass "$name (exit $rc)"
        [ -n "$out" ] && note "${out:0:400}"
    else
        fail "$name" "expected exit $expected_exit, got $rc"
        note "${out:0:600}"
    fi
    return 0
}

# Clean up any stale termiclaw containers first.
docker ps -a --filter name=termiclaw -q | xargs -r docker rm -f >/dev/null 2>&1

# Startup check: Docker + Claude Code available.
if ! docker info >/dev/null 2>&1; then
    skip "prerequisites" "docker daemon not running"
    exit 0
fi
if ! command -v claude >/dev/null 2>&1; then
    skip "prerequisites" "claude CLI not on PATH"
    exit 0
fi

# Scratch dir for artifacts created during the smoke.
scratch=$(mktemp -d -t termiclaw-e2e-XXXXXX)
trap 'rm -rf "$scratch"' EXIT

# ---------------------------------------------------------------
# 1. Read-only + error-path subcommands
# ---------------------------------------------------------------
run_case "--help"              0 tc --help
run_case "list"                0 tc list
run_case "status"              0 tc status
run_case "failures"            0 tc failures
run_case "mcts-show missing"   1 tc mcts-show does_not_exist
run_case "tag unknown category" 1 tc tag xxxxxxxx --category bogus_cat
run_case "eval missing dir"    1 tc eval /tmp/termiclaw-nope-$$
run_case "fork missing run"    1 tc fork does_not_exist_run --task "nothing"
run_case "show missing run"    1 tc show does_not_exist_run
run_case "export missing run"  1 tc export does_not_exist_run --format atif

# ---------------------------------------------------------------
# 2. Live run: concrete file-creation inside the ephemeral container.
# The container is destroyed after success, so we can't probe the host
# filesystem — we assert on trajectory/metadata instead.
# ---------------------------------------------------------------
target_in_container="/tmp/termiclaw-e2e-$$.txt"
run_case "run simple task" 0 tc run \
    "Create the file $target_in_container. Write exactly the literal text 'e2e ok' to it using echo, then confirm with cat. Do not set task_complete=true until the terminal shows the cat output containing 'e2e ok'." \
    --max-turns 10

# Capture the most recent run id for downstream checks.
latest_run=$(tc list 2>&1 | awk 'NR>2 {print $1; exit}')

# ---------------------------------------------------------------
# 3. Run metadata + trajectory sanity (regression for BUG-41 / BUG-42)
# ---------------------------------------------------------------
if [ -n "$latest_run" ]; then
    run_json=$(ls -1 "./termiclaw_runs/${latest_run}"*/run.json 2>/dev/null | head -1)
    traj=$(ls -1 "./termiclaw_runs/${latest_run}"*/trajectory.jsonl 2>/dev/null | head -1)
    if [ -n "$run_json" ] && [ -f "$run_json" ]; then
        meta=$(python3 <<PY
import json
d = json.load(open("$run_json"))
print(d.get("total_steps", -1))
print(d.get("status", ""))
print(d.get("termination_reason", ""))
PY
)
        steps_meta=$(printf "%s\n" "$meta" | sed -n 1p)
        status_meta=$(printf "%s\n" "$meta" | sed -n 2p)
        term_meta=$(printf "%s\n" "$meta" | sed -n 3p)
        steps_traj=$(wc -l < "$traj" | tr -d ' ')
        if [ "$steps_meta" = "$steps_traj" ] && [ "$steps_meta" -gt 0 ]; then
            pass "BUG-41 regression: step counter matches trajectory ($steps_meta)"
        else
            fail "step counter (BUG-41 regression)" "meta=$steps_meta traj=$steps_traj"
        fi
        [ "$status_meta" = "succeeded" ] && pass "run status=succeeded" \
            || fail "run status" "expected succeeded, got $status_meta"
        [ "$term_meta" = "task_complete_confirmed" ] && pass "termination_reason=$term_meta" \
            || fail "termination_reason" "expected task_complete_confirmed, got $term_meta"

        # BUG-42 regression: trajectory keystrokes must contain the
        # literal single-quoted payload *without* shlex escape sequences
        # like `'"'"'` which would mean shlex.quote crept back in.
        if python3 <<PY
import json, sys
ok = False
bad = False
for line in open("$traj"):
    d = json.loads(line)
    for c in (d.get("tool_calls") or []):
        k = (c.get("arguments") or {}).get("keystrokes", "")
        if "'\"'\"'" in k:
            bad = True
        if "echo 'e2e ok'" in k:
            ok = True
sys.exit(0 if ok and not bad else 1)
PY
        then
            pass "BUG-42 regression: trajectory keystrokes passed verbatim (no shlex quoting)"
        else
            fail "keystroke passthrough (BUG-42 regression)" "quoting artefacts or missing target command in trajectory"
        fi

        # BUG-43 regression: at least one agent-source step must carry a
        # non-empty terminal_output. Pre-fix, _log_agent_step was called
        # with "" and every trajectory step shipped blank observations.
        if python3 <<PY
import json, sys
for line in open("$traj"):
    d = json.loads(line)
    if d.get("source") != "agent":
        continue
    obs = (d.get("observation") or {}).get("terminal_output", "")
    if obs:
        sys.exit(0)
sys.exit(1)
PY
        then
            pass "BUG-43 regression: trajectory carries non-empty observation"
        else
            fail "observation passthrough (BUG-43 regression)" "every agent step has empty terminal_output"
        fi
    else
        fail "run metadata" "run.json not found under termiclaw_runs/${latest_run}*"
    fi
fi

# ---------------------------------------------------------------
# 4. Show / export / tag roundtrip
# ---------------------------------------------------------------
if [ -n "$latest_run" ]; then
    run_case "show <run-id>"      0 tc show "$latest_run"
    run_case "export atif"        0 tc export "$latest_run" --format atif
    atif_file=$(ls -1 "./termiclaw_runs/${latest_run}"*"/${latest_run}"*.atif.json 2>/dev/null | head -1)
    if [ -n "$atif_file" ] && python3 -c "import json; json.load(open('$atif_file'))" 2>/dev/null; then
        pass "atif JSON parses"
        # Verify the ATIF top-level keys this codebase actually emits
        # (schema_version + per-run fields — see termiclaw/atif.py).
        if python3 -c "
import json, sys
d = json.load(open('$atif_file'))
for k in ('schema_version', 'run_id', 'status', 'steps', 'instruction'):
    if k not in d:
        sys.exit(f'missing {k}')
" 2>/dev/null; then
            pass "atif schema (top-level keys)"
        else
            fail "atif schema" "missing required top-level keys"
        fi
    else
        fail "atif JSON" "missing or unparseable: $atif_file"
    fi
    run_case "tag <run-id>"       0 tc tag "$latest_run" --category stuck_loop --note "smoke"
    run_case "failures histogram" 0 tc failures
    failures_out=$(tc failures 2>&1)
    if printf "%s" "$failures_out" | grep -q "stuck_loop"; then
        pass "tagged failure surfaced in histogram"
    else
        fail "tagged failure" "stuck_loop missing from failures output"
    fi
else
    skip "post-run checks" "no completed run found"
fi

# ---------------------------------------------------------------
# 5. Fork smoke (requires a succeeded run)
# ---------------------------------------------------------------
if [ -n "$latest_run" ]; then
    fork_target="/tmp/termiclaw-fork-$$.txt"
    run_case "fork existing run"  0 tc fork "$latest_run" \
        --task "Create $fork_target with the single word 'forked' inside. Do not set task_complete=true until cat $fork_target prints 'forked'." \
        --max-turns 6
    # Pick the newest run other than $latest_run to assert on.
    fork_run=$(tc list 2>&1 | awk -v orig="$latest_run" 'NR>2 && $1!=orig {print $1; exit}')
    if [ -n "$fork_run" ]; then
        fork_json=$(ls -1 "./termiclaw_runs/${fork_run}"*/run.json 2>/dev/null | head -1)
        if [ -n "$fork_json" ]; then
            fs=$(python3 -c "import json; d=json.load(open('$fork_json')); print(d.get('status',''))")
            [ "$fs" = "succeeded" ] && pass "fork run succeeded" \
                || fail "fork status" "expected succeeded, got $fs"
        else
            fail "fork metadata" "run.json not found for $fork_run"
        fi
    else
        fail "fork run discovery" "no new run id appeared after fork"
    fi
fi

# ---------------------------------------------------------------
# 6. Eval over a tiny task dir (one trivial verifier-equipped task)
# ---------------------------------------------------------------
tasks_dir="$scratch/tasks"
mkdir -p "$tasks_dir"
cat > "$tasks_dir/hello.toml" <<EOF
instruction = "Create /tmp/termiclaw-eval-$$.txt with the single word 'evalok' inside. Confirm with cat before marking complete."

[verifier]
command = "cat /tmp/termiclaw-eval-$$.txt"
expected_exit = 0
expected_output_pattern = "evalok"
timeout_seconds = 5
EOF
run_case "eval one-task dir"   0 tc eval "$tasks_dir" --max-turns 8 --parallelism 1
rm -f "/tmp/termiclaw-eval-$$.txt"

# ---------------------------------------------------------------
# Summary
# ---------------------------------------------------------------
note ""
note "================================"
note "e2e smoke: $pass_count pass, $fail_count fail"
note "================================"
for r in "${results[@]}"; do note "$r"; done

if [ "$fail_count" -gt 0 ]; then
    exit 1
fi
