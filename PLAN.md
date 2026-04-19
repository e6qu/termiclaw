# Termiclaw Roadmap

Living planning doc. Design discussions for shipped features live in
[docs/DESIGN.md](docs/DESIGN.md); this file tracks what's shipped and
what's next.

## Last shipped: v1.4 (functional-core / imperative-shell split)

v1.4 is a type-safety + correctness release. No new features, but the
functional-core refactor surfaced a pile of loop bugs that had been
hiding behind mutable state — BUG-33..BUG-43 all landed as part of
v1.4 (see `BUGS.md`). The agent loop is now a thin imperative shell
over a pure `decide` core plus a typed `apply` dispatch through
`Ports` Protocols. `RunState` is now `State` (frozen, slotted). Sum
types (`Command`, `Event`) have exhaustive-match enforcement.

## Next release: v1.5 (planning)

Candidates (user to pick order): autoresearch driver, ATIF import,
step-granular MCTS replay, Docker image publish to ghcr.

## Lint rules in force

Guards run in `.pre-commit-config.yaml` and fail the pre-commit stage:

- **`scripts/check-no-object-in-signatures.sh`** — forbids `object` /
  `Any` in type annotations outside the boundary allowlist
  (`validate.py`, `planner.py`, `task_file.py`, `atif.py`).
- **`scripts/check-no-monkeypatch.sh`** — forbids the `monkeypatch`
  fixture anywhere in the repo. Tests exercise production code through
  real injection seams: env vars (`TERMICLAW_DB_PATH`,
  `TERMICLAW_SKIP_UPDATE_CHECK`), constructor params
  (`MctsSearch.agent_run: AgentRun`), `main(argv=...)`, and `Ports`
  Protocols. If code feels hard to test without `monkeypatch`,
  refactor the seam into the production API.
- **`scripts/check-exhaustive-match.sh`** — forbids `case _:` in
  `termiclaw/decide.py` and `termiclaw/shell.py`. The match statements
  there dispatch over closed sum types (`Event` / `Command`); a
  default arm silently swallows new variants.
- **`scripts/check-log-reserved-names.sh`** — forbids reserved
  `LogRecord` attribute names (`name`, `msg`, `args`, …) as keys in
  `extra=` dicts; collision crashes the logger (see BUG-33).
- **`scripts/check-no-shlex-quote-in-argv.sh`** — forbids
  `shlex.quote(…)` anywhere under `termiclaw/` without a
  `# shlex-quote-ok` opt-in. Quoting inside a `subprocess.run([...])`
  list-mode call only injects literal quote characters into the
  callee's argv (see BUG-15, BUG-42).
- **Imports at top of file (ruff `PLC0415`)** — enforced everywhere,
  tests included. Move inline imports to the module header.
- **No `Any`, no `object` in public signatures, no `type: ignore`
  anywhere.** Production code narrows via `validate.py` combinators
  at the JSON boundary; tests exercise runtime-typed attribute tricks
  via `setattr()` when they need to probe frozen-dataclass behavior.

## Principles

1. **Match Terminus-2 parameters when cheap; diverge deliberately when the CLI backend forces it.** Documented in docs/DESIGN.md.
2. **Self-unblocking is termiclaw's own territory.** Terminus-2 does not implement stall detection; our nudge/force-interrupt escalation is a genuine addition.
3. **Thresholds are in tokens.** `planner.extract_usage` is the source of truth; chars are debug-only.
4. **Prefer native Claude Code capabilities.** `--fork-session`, `--resume`, `--session-id`, `--json-schema`, `--append-system-prompt`, `--no-session-persistence` before reinventing.
5. **No feature flags.** Features are always on once shipped. Rollback = revert the commit.
6. **No fallbacks. No dead code. No parallel codepaths.** One primary mechanism per concern. If the primary fails, surface the error.
7. **No modes.** No orthogonal axes of behavior selectable at configuration time. Dispatch by fixed rule is acceptable; user-facing mode booleans are not.
8. **Every feature lands with telemetry.** New SQLite columns or step-metric keys so we can measure before/after.
9. **No new runtime dependencies.** stdlib only.

## Non-goals

- **No non-Claude backends.** Claude Code is the only planner interface.
- **No custom tokenizers.** `planner.extract_usage` ground truth is the stack.
- **No multi-agent orchestration.** One planner, one execution environment, one run.
- **No hosted service / web UI.**
- **No Docker image publishing to ghcr.** Local-build only; future ops task.
- **Autoresearch automation is deferred.** Scoring/tagging primitives shipped in v1.3; the eval→tag→tweak driver loop is a v1.5+ candidate.

## Shipped (v0.8 → v1.4)

| Version | Feature                                            | Notes                                      |
|---------|----------------------------------------------------|--------------------------------------------|
| v0.9    | `Config.max_command_length` wired to `send_keys`   | Was dead parameter. |
| v0.9    | Token-based context accounting                     | `extract_usage` → per-call counts on `RunState`; chars are secondary. |
| v0.9    | `--json-schema` structured output                  | Claude-side validation of the envelope schema. |
| v0.10   | Agent must self-unblock                            | Stall hash → nudge → force-interrupt escalation. |
| v0.10   | Full scrollback capture                            | `capture-pane -S -`, fallback-free. |
| v0.10   | Shell-quoted keystrokes (initial)                  | Added `mode="literal"` then removed in v1.0. |
| v0.11   | Blocking command wait (initial)                    | `; tmux wait -S done` wrapper; removed as a flag in v1.0. |
| v0.11   | State-dump artifacts                               | `WHAT_WE_DID.md` / `STATUS.md` / `DO_NEXT.md` / per-run `PLAN.md`. |
| v0.12   | Session forking via `--fork-session`               | Native Claude Code flag; seed from artifacts. |
| v1.0    | Docker-only execution                              | Deleted `termiclaw/tmux.py`. |
| v1.0    | Modes purge                                        | Removed `ParsedCommand.mode`, `block_until_idle`, `environment`. |
| v1.0    | API freeze                                         | `Config` stabilized; subsequent changes are additive. |
| v1.1    | Result[T,E] types                                  | PEP 695 generics; callers pattern-match `Ok`/`Err`. |
| v1.1    | Custom exception hierarchy                         | `TermiclawError` + subclasses; no bare Exception. |
| v1.1    | Validator combinators                              | `termiclaw.validate` narrows `dict[str, object]` at the JSON boundary. |
| v1.2    | Task verifier                                      | Bash exit-code verifier; `[verifier]` TOML section. |
| v1.2    | `termiclaw eval <dir>`                             | Runs a directory of task TOMLs, reports pass/fail. |
| v1.2    | MCTS scaffolding                                   | `MctsSearch`, UCB1, parallel playouts — but forks were mocked. |
| v1.3    | MCTS real forks                                    | `--fork-session` on child's first planner call; SQLite persistence. |
| v1.3    | `termiclaw mcts-show <search-id>`                  | ASCII tree view of an MCTS search. |
| v1.3    | ATIF v1.6 export                                   | `termiclaw export <run-id> --format atif`. |
| v1.3    | Failure tagging                                    | `termiclaw tag <run-id> --category …`; `termiclaw failures`. |
| v1.3    | Async summarization (BUG-29)                       | `SummarizationWorker` runs the 3-subagent pipeline off-path. |
| v1.3    | object/Any pre-commit ban                          | `scripts/check-no-object-in-signatures.sh`. |
| v1.4    | Frozen `State` + `ForkContext`                     | `termiclaw/state.py`; all mutations via `dataclasses.replace` or `with_*` helpers. |
| v1.4    | Pure `decide` + `apply` shell                      | `termiclaw/decide.py`, `termiclaw/shell.py`; `Transition` product; exhaustive match on `Event`/`Command`. |
| v1.4    | `Ports` Protocol bundle                            | `termiclaw/ports.py`, `termiclaw/runtime.py`; tests use `tests/unit/fakes/` (no `mock.patch` of internals). |
| v1.4    | Lint: no-monkeypatch + exhaustive-match guards     | Added to pre-commit alongside object/Any ban. |
| v1.4    | Live e2e shakeout bugfixes                         | BUG-33..44 — see `BUGS.md`. Added reserved-logrecord + shlex-quote pre-commit guards. |
| v1.4    | Ports for provisioning (W7 follow-up)              | `container.ensure_image` / `provision_container` / `provision_session` / `destroy_container` behind `ContainerPort`; `mock.patch` of provisioning internals gone from the unit suite. |

## After v1.4

Candidates, roughly ordered; user reprioritizes as needed:

1. **Autoresearch driver** — promote the v1.3 failure-tagging and
   eval primitives into an automated `eval → tag histogram → prompt
   tweak → rerun` loop.
2. **Step-granular MCTS replay** — Docker container
   commit/checkpoint so MCTS forks at tmux step N, not only at the
   Claude session level.
3. **ATIF import** — ingest trajectories from other harnesses so
   MCTS / eval / replay can be seeded from external runs.
4. **Docker image publish to ghcr** — turnkey install; drop the
   local-build-on-first-run step for most users.

## Dropped

- **Chat history fallback** — violated principle #6 (no fallbacks).
- **Mode-switching keystroke encoding** — violated principle #7 (no
  modes). v1.0 collapsed to one dispatch rule.
- **tiktoken pre-flight** — violated principle #9 (no new deps).
  `planner.extract_usage` ground truth + `len // 4` estimate is the
  whole token stack.
