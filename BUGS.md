# Bugs

Report new issues at <https://github.com/e6qu/termiclaw/issues>.

## Open

*(none)*

## Resolved

| ID | Severity | Summary | Resolved in |
|---:|----------|---------|-------------|
| 1 | Critical | `run_id` not propagated to log output | v0.6 |
| 2 | Critical | Special tmux keys (`C-c`, `Enter`) shell-quoted into literal text | v0.8 |
| 3 | Critical | Summarization `query_fn` returned JSON envelope instead of text | v0.8 |
| 4 | Critical | Summarization received placeholder instead of step history | v0.8 |
| 5 | Medium | `--allowedTools` missing from `claude -p` invocation | v0.8 |
| 6 | Medium | `--verbose` flag parsed but never wired | v0.8 |
| 7 | Medium | Misleading import ordering in `agent.py` | v0.8 |
| 8 | Medium | No wait after tmux provisioning | v0.8 |
| 9 | Low | `truncate_output` split mid-UTF-8 character | v0.8 |
| 12 | Low | `_execute_commands` sleeps with zero commands | v0.8 |
| 13 | Critical | Prompt ambiguous about `\n` vs separate `Enter` commands | v0.8 |
| 14 | Critical | Failed planner calls not logged in trajectory | v0.8 |
| 15 | Critical | `_split_keys` used `shlex.quote` but subprocess list mode bypasses shell | v0.8 (partial — see BUG-42: this call site was never actually changed; fully resolved in v1.4) |
| 16 | Medium | `attach` didn't handle short prefixes or missing sessions | v0.8 |
| 17 | Medium | `--task` with nonexistent file gave raw traceback | v0.8 |
| 18 | Medium | Summarization step bypassed `_track_step` | v0.8 |
| 19 | Medium | tmux provisioning failure crashed with no metadata | v0.8 |
| 20 | Medium | `setup_logging` handler accumulates in tests | v0.8 |
| 21 | Low | `format_steps_text` used full 32-char UUID | v0.8 |
| 22 | Low | Closing-brace fixer didn't handle missing `]` | v0.8 |
| 25 | Medium | No "Run finished" log on provision failure | v0.8 |
| 26 | Medium | Duplicate `}]}` suffix in brace fixer | v0.8 |
| 27 | Medium | `recent_steps_text` and `full_steps_text` identical in summarization | v0.8 |
| 28 | Low | `capture_full_history` unbounded memory on long sessions | v0.8 |
| 29 | Medium | Summarization blocked main loop for up to 15 min | v1.3 (async worker) |
| 30 | Low | Observation prefix ate into 200-char preview budget | v0.8 |
| 31 | Medium | "Run finished" log skipped on unexpected exceptions | v0.8 |
| 32 | Low | `read_trajectory_text` crashed on non-dict observation | v0.8 |
| 33 | Critical | `container.provision_container` logged `extra={"name": ...}`, collision with reserved `LogRecord.name` crashed every run | v1.4 |
| 34 | Critical | `decide._on_planner_failed` emitted `ObserveCmd`, creating an inner `QueryPlanner → PlannerFailed → Observe → QueryPlanner` cycle that ignored `max_turns` | v1.4 |
| 35 | Critical | `is_first_call` never cleared on planner failure — retries re-asserted `--session-id` with an id Claude CLI had already reserved; loop never recovered | v1.4 |
| 36 | Critical | `claude -p --max-turns 1` exits non-zero with `subtype=error_max_turns` when `--json-schema` enforcement needs ≥2 turns; every planner call failed | v1.4 (raised to `--max-turns 4`) |
| 37 | Critical | `--json-schema` puts the parsed object in `envelope["structured_output"]`, not `envelope["result"]`. Parser read `result`, found empty string, failed every turn | v1.4 |
| 38 | Critical | `StepLogged` event carried no step; `decide._on_step_logged` never called `with_step`, so `state.current_step` stayed 0 for the whole run | v1.4 |
| 39 | Critical | `_drive` exited as soon as `state.status != "active"`, dropping any terminal `LogStepCmd` emitted by confirmed completion (final step never written) | v1.4 |
| 40 | Critical | `_drive` prepended sub-decide commands onto `pending`, so `LogStepCmd` siblings queued in the same outer batch waited behind arbitrarily-deep sub-chains; on a two-cmd planner response the log step never ran before the next planner call and the run hung | v1.4 (append instead) |
| 41 | Medium | `_drive` gated sub-command enqueue on post-decide status; the terminal `LogStepCmd` emitted *alongside* the `"active" → "succeeded"` transition was therefore dropped, so the confirmation step never reached the trajectory and `total_steps` stayed 0 in run metadata | v1.4 (gate on pre-apply `was_active`; always re-decide so `StepLogged` bumps `current_step`) |
| 42 | Critical | `send_keys` applied `shlex.quote(chunk)` before passing to `subprocess.run([...])` — list mode bypasses the shell, so tmux received the literal `'echo '"'"'…'"'"' …'` wrapper and typed the quote characters into the bash session, mangling every non-trivial command. Identical in character to BUG-15 (which was marked resolved in v0.8 but this call site was never actually changed) | v1.4 (pass `chunk` verbatim; add regression tests for literal passthrough and embedded-single-quote payloads) |
| 43 | Medium | `_log_agent_step` was always called with `observation=""` — every agent-source step shipped empty `terminal_output` in trajectory + ATIF, losing the diff captured at `_on_observation` and badly damaging replay / eval fidelity | v1.4 (thread `text` → `state.last_observation` at ObservationCaptured, consume + clear in `_on_planner_responded` / `_handle_completion`) |

## False positives

| ID | Claimed bug | Why it's correct |
|---:|-------------|------------------|
| 10 | `_strip_code_fences` only handles single-layer fencing | stage-4 extractor catches nested fences |
| 11 | `_check_field_order` silently ignores extra/missing fields | extras are valid, missing fields are optional |
| 23 | `\\n` in prompt template looks like double-escape | correct Python string escape for literal `\n` |
| 24 | `_check_field_order` uses O(n) `list.index()` | n=m=4, negligible |
