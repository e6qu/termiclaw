# Bugs

## Fixed

| ID | Severity | Summary | File | Fix |
|----|----------|---------|------|-----|
| 1 | Critical | `run_id` never included in log output | logging.py | Added `"run_id": _run_id` to formatter |
| 2 | Critical | Special tmux keys (`C-c`, `Enter`) shell-quoted into literal text | tmux.py | Regex detection + `-l` flag for literal text |
| 3 | Critical | Summarization query_fn returned JSON envelope instead of text | agent.py | Direct `envelope.get("result")` extraction |
| 4 | Critical | Summarization received placeholder instead of step history | agent.py, models.py | `recent_steps` field + `read_trajectory_text()` |
| 5 | Medium | `--allowedTools` missing from `claude -p` invocation | planner.py | Added `"--allowedTools", ""` to command |
| 6 | Medium | `--verbose` flag parsed but never wired | cli.py, agent.py, models.py | Config.verbose → setup_logging level |
| 7 | Medium | Misleading import ordering in agent.py | agent.py | Reordered imports above TYPE_CHECKING block |
| 8 | Medium | No wait after tmux provisioning | agent.py | Added `time.sleep(0.5)` |
| 9 | Low | `truncate_output` split mid-UTF-8 character | tmux.py | Switched to character-level slicing |
| 10 | Low | `_strip_code_fences` only handles single-layer | planner.py | Accepted — stage 4 fallback handles it |
| 11 | Low | `_check_field_order` silently ignores extra fields | planner.py | Accepted — behavior is correct |
| 12 | Low | `_execute_commands` sleeps with zero commands | agent.py | Added early return |
| 13 | Critical | Prompt ambiguous about `\n` vs separate `Enter` commands | planner.py | Clarified template: one command per object |
| 14 | Critical | Failed planner calls not logged in trajectory | agent.py | StepRecord written on RuntimeError |
| 15 | Critical | `_split_keys` used `shlex.quote` but subprocess list mode bypasses shell | tmux.py | Byte-length estimation, removed shlex, raised limit to 200KB |
| 16 | Medium | `attach` didn't handle short prefixes or missing sessions | cli.py | Prefix matching via `tmux list-sessions` |
| 17 | Medium | `--task` with nonexistent file gave raw traceback | cli.py | Path existence check before read |
| 18 | Medium | Summarization step bypassed `_track_step` | agent.py | Uses `_track_step` consistently |
| 19 | Medium | tmux provisioning failure crashed with no metadata | agent.py | Catch CalledProcessError, write metadata, return |
| 20 | Medium | `setup_logging` handler accumulates in tests | logging.py | Test-only — cleanup in fixtures |
| 21 | Low | `format_steps_text` used full 32-char UUID | summarizer.py | Truncated to `[:8]` |
| 22 | Low | Closing brace fixer didn't handle missing `]` | planner.py | Added `]}`, `]}}`, `}]}` variants |
| 25 | Medium | No "Run finished" log on provision failure | agent.py | Added log before early return |
| 26 | Medium | Duplicate `}]}` suffix in brace fixer | planner.py | Removed duplicate |
| 27 | Medium | `recent_steps_text` and `full_steps_text` identical in summarization | agent.py, trajectory.py | Added `read_trajectory_text()` for full history |
| 28 | Low | `capture_full_history` unbounded memory on long sessions | tmux.py | Limited to last 10,000 lines |
| 30 | Low | Observation prefix ate into 200-char preview budget | summarizer.py | Strip prefix before previewing |
| 31 | Medium | "Run finished" log skipped on unexpected exceptions | agent.py | Moved log inside `finally` block |
| 32 | Low | `read_trajectory_text` crashed on non-dict observation | trajectory.py | `isinstance` check before `.get()` |

## Open

### BUG-29: Summarization blocks main loop during 3 sequential LLM calls

**File**: `termiclaw/agent.py:224-266`

When summarization triggers, `query_fn` makes up to 3 sequential `claude -p` calls, each with 300s timeout. The agent is blocked for up to 15 minutes. During this time the tmux session isn't monitored, no progress is reported, and `is_session_alive` doesn't run.

Matches Terminus behavior (synchronous summarization). Would need async or a pipeline timeout to fix.

---

(None — all open bugs have been fixed except BUG-29 which is a known design limitation matching Terminus.)

## False Positives

| ID | Summary | Reason |
|----|---------|--------|
| 23 | `\\n` in prompt template looks like double-escape | Correct Python string escaping for `\n` in format string |
| 24 | `_check_field_order` uses O(n) `list.index()` | n=4, m=4 — negligible |
| 10 | `_strip_code_fences` only handles single-layer fencing | Stage 4 (`_try_extract_json`) catches these as fallback |
| 11 | `_check_field_order` silently ignores extra/missing fields | Intended behavior — extra fields are valid, missing fields are optional |
