# Termiclaw Specification

## A Terminus-style terminal agent using Claude Code as the planner

Source in `termiclaw/` is authoritative for *what* the code does; this file is the *why* and the non-functional contract. For the architectural comparison against Terminus, see [docs/DESIGN.md](docs/DESIGN.md). For the shipped-per-version log and roadmap, see [PLAN.md](PLAN.md).

---

## 1. Purpose

Termiclaw is a terminal agent that controls a tmux session through keystrokes, using Claude Code (`claude -p`) as a stateless structured planner. It follows the Terminus-2 observe-decide-act loop faithfully, adapted for Claude Code subscription-based usage.

The agent:

* runs outside the terminal it controls
* sends raw keystrokes to a single tmux pane inside a Docker container
* captures terminal output via `tmux capture-pane`
* queries `claude -p` for the next action each step
* owns all context management (stateless planner calls)
* summarizes on a background thread when approaching context limits
* logs every step in ATIF-style JSONL trajectory files
* self-unblocks on stalls (hashed observation + keystroke streak → nudge → force-interrupt)

---

## 2. Design principles

Taken directly from Terminus-1, sharpened in v1.0 onwards:

* **One tool: the terminal.** All interaction flows through tmux keystrokes. No file read tools, no bash tools, no websearch tools. The agent types what a human would type.
* **Planner outside the runtime.** The planner (Claude Code) never executes anything. It returns structured decisions. The orchestrator executes them.
* **Single pane.** One tmux session, one window, one pane per run.
* **Resilient parsing.** Malformed planner output does not crash the loop. Parse errors are fed back as the next prompt.
* **Summarization is core, not optional.** Long runs require context compression. Three-subagent summarization pipeline, running asynchronously so stall detection keeps observing.
* **Keystroke-only action model.** No action type abstraction. Commands are `keystrokes` + `duration`. This is the Terminus model.
* **Functional core / imperative shell.** The decision logic (`termiclaw/decide.py`) is pure: `decide(state, event, config, effects) -> Transition`. Side effects go through a typed `Ports` bundle in `termiclaw/shell.py`'s `apply(cmd, ports) -> event`. State is a frozen dataclass.
* **No feature flags, no fallbacks, no modes, no dead code.** One primary mechanism per concern; if it fails, surface the error. See [PLAN.md](PLAN.md) for the full list of standing principles.

---

## 3. System context

```
┌─────────────────────────────────────────────┐
│                  Operator                    │
│         termiclaw run "..."                  │
│         termiclaw attach <run-id>            │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Termiclaw agent                 │
│  (host Python, stdlib only)                  │
│                                              │
│  agent.run() ─▶ decide() ─▶ apply() ─▶ loop │
│                                              │
│  ports: container / planner / persistence    │
│         / artifacts / summarize              │
└──────────────────┬──────────────────────────┘
                   │ docker exec
┌──────────────────▼──────────────────────────┐
│         Docker container (per run)           │
│   termiclaw-base:<sha256[:12]>               │
│   ubuntu:24.04 + tmux + asciinema            │
│                                              │
│   tmux session termiclaw-<run_id_short>      │
│   single pane: bash --login                  │
│   160 x 40, history-limit 10_000_000         │
└─────────────────────────────────────────────┘
```

Source of truth: `termiclaw/agent.py`, `termiclaw/decide.py`, `termiclaw/shell.py`, `termiclaw/ports.py`, `termiclaw/container.py`.

---

## 4. Agent loop

The top-level loop is a translation of Terminus-2's `_run_agent_loop`, restructured around an explicit decide/apply split.

Per iteration (capped by `Config.max_turns`, default 1,000,000):

1. The shell pre-computes two signals: is the tmux session alive, and is the summarization worker ready for a new job.
2. The shell polls the background summarization worker. If it has a result, that becomes the next event; otherwise a `LoopTick(summarize_ready, session_alive)` is synthesized.
3. `decide(state, event, config, effects)` returns a `Transition(state', commands)`. Pure function — no I/O.
4. For each command in the batch, the shell calls `apply(cmd, ports, state, run_dir, config)` which performs the side effect and returns the resulting `Event`. That event feeds back through `decide`; any new commands prepend onto the queue.
5. When the queue empties, the outer turn completes; the next top-of-loop tick starts.

Loop exits when `State.status != "active"` (succeeded / failed / cancelled) or `max_turns` is exhausted.

Key invariants:

* Exactly one planner call per decide → apply cycle (retries live inside the `PlannerPort`).
* Parse failures loop back as the next prompt without executing anything.
* Double-finish confirmation is required for `task_complete`.
* Stall detection runs every iteration against the observation + keystroke hashes; crossing the nudge threshold prepends a system notice; crossing the force-interrupt threshold sends `C-c`.
* Summarization runs on a background thread; the main loop never blocks on it.

See [docs/DESIGN.md](docs/DESIGN.md) §3 for the diff against Terminus-2.

---

## 5. Non-functional requirements

### 5.1 Packaging

* `uv` as package manager; `hatchling` build backend; `uv.lock` committed
* Dependency groups: `test`, `lint`, `typecheck`, `dev` (meta)
* **Zero runtime dependencies** — only dev/test tooling is external

### 5.2 Type checking

* `ty` (Astral's type checker) with strict settings, clean on every commit
* **No use of `Any`, `object` in public signatures, `cast`, or `type: ignore` anywhere.** The only places `object` is allowed in a type annotation are the JSON-boundary modules: `termiclaw/validate.py`, `planner.py`, `task_file.py`, `atif.py`. Enforced by `scripts/check-no-object-in-signatures.sh` in pre-commit.
* All functions fully annotated with return types; domain objects as typed `dataclasses`.
* All `dict` types must be parameterized (`dict[str, int]`, not bare `dict`).

### 5.3 Linting and formatting

* `ruff` as both linter and formatter with a comprehensive rule set (`A`, `ANN`, `ARG`, `B`, `BLE`, `C4`, `C90`, `DTZ`, `E`, `EM`, `ERA`, `F`, `FBT`, `I`, `ICN`, `ISC`, `N`, `PGH`, `PIE`, `PL`, `PT`, `PTH`, `RET`, `RSE`, `RUF`, `S`, `SIM`, `SLF`, `T20`, `TCH`, `TID`, `TRY`, `UP`, `W`, `YTT`).
* Per-file ignores kept narrow; no blanket disables.
* Max cyclomatic complexity: 10 (mccabe).
* Imports at top of every file (`PLC0415` enforced everywhere, tests included).

### 5.4 Testing

* `pytest` with `pytest-cov`, branch coverage enabled.
* Coverage ≥ **84%** enforced in CI; pre-push hook runs the full suite.
* No `mock.patch` of production internals in unit tests. `scripts/check-no-monkeypatch.sh` forbids pytest's `monkeypatch` fixture; tests inject via real seams (env vars, constructor params, `main(argv=...)`, `Ports`).
* Exhaustive-match discipline enforced in `termiclaw/decide.py` and `shell.py`: no `case _:` default arms (`scripts/check-exhaustive-match.sh`).

### 5.5 Observability

Structured JSONL logging to stderr and a per-run file. Every log line includes `ts`, `level`, `run_id`, `component`, `msg` — additional fields vary by component. Log files live at:
* macOS: `~/Library/Logs/termiclaw/<run-id>.jsonl`
* Linux: `~/.local/state/termiclaw/log/<run-id>.jsonl`

No `print()` statements anywhere in `termiclaw/` — all output goes through `termiclaw/logging.py` or the CLI's stderr writers.

---

## 6. Evals, benchmarking, and autoresearch

Shipped primitives (v1.2–v1.3):

* **`termiclaw eval <dir>`** — runs a directory of TOML task files, reports pass/fail; each task carries a `[verifier]` section (`command`, `expected_exit`, optional `expected_output_pattern`).
* **`termiclaw mcts --task <toml>`** — Monte-Carlo Tree Search over forks of a task, scored by the verifier; real forks use `--fork-session`.
* **`termiclaw mcts-show <search-id>`** — ASCII tree of a persisted search.
* **`termiclaw export <run-id> --format atif`** — ATIF v1.6 trajectory export for Terminal-Bench submission.
* **`termiclaw tag <run-id> --category <name>`** + **`termiclaw failures`** — closed-set failure categorization (`premature_completion`, `parse_failure`, `wrong_command`, `stuck_loop`, `timeout`, `hallucination`, `container_error`, `verifier_failure`) with histogram reporting.

Deferred: the autoresearch driver (an automated `eval → tag histogram → prompt tweak → rerun` loop over the primitives above) — see [PLAN.md](PLAN.md) "After v1.4".

References:
* Terminal-Bench: <https://www.tbench.ai/>
* ATIF v1.6: [harbor RFC 0001](https://github.com/laude-institute/harbor/blob/main/docs/rfcs/0001-trajectory-format.md)
* AutoResearch pattern: <https://github.com/karpathy/autoresearch>
* Evaluation-Driven Development: <https://arxiv.org/html/2411.13768v3>

---

## 7. Acceptance criteria

The release is acceptable when all of these hold:

* `termiclaw run "create a file called hello.txt with 'hello world' in it"` successfully creates the file via tmux keystrokes inside a container.
* The operator can `termiclaw attach <run-id>` during a run and watch commands being typed.
* The trajectory JSONL contains every step with observations and actions.
* Parse errors from the planner are recovered from without crashing; failed planner calls are logged as steps.
* A long-running task triggers summarization on the background thread and continues successfully without blocking observation.
* Double-finish confirmation prevents premature completion.
* Ctrl-C during a run writes final state and (unless `--keep-session`) destroys the container.
* Stall detection escalates to `C-c` after the configured streaks; ultimate failure after `max_forced_interrupts_per_run`.
* The entire project is stdlib-only Python 3.13.
* All code passes `ruff check`, `ruff format --check`, and `ty check` with zero warnings.
* All pre-commit guards pass: `no-object-signatures`, `no-monkeypatch`, `exhaustive-match`, `no-reserved-logrecord-keys`, `no-shlex-quote-in-argv`.
* Test coverage ≥ 84% with branch coverage.
* All logging is structured JSONL — no `print()` in `termiclaw/`.
* No `Any`, `cast`, or `type: ignore` in the codebase.
* Code exhaustively pattern-matches on the `Command` and `Event` sum types in `decide.py` / `shell.py`.
