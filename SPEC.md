# Termiclaw Specification

## A Terminus-style terminal agent using Claude Code as the planner

---

## 1. Purpose

Termiclaw is a terminal agent that controls a tmux session through keystrokes, using Claude Code (`claude -p`) as a stateless structured planner. It follows the Terminus-2 observe-decide-act loop faithfully, adapted for Claude Code subscription-based usage.

The agent:

* runs outside the terminal it controls
* sends raw keystrokes to a single tmux pane
* captures terminal output via `tmux capture-pane`
* queries `claude -p` for the next action each step
* owns all context management (stateless planner calls)
* summarizes when approaching context limits
* logs every step in ATIF-style JSONL trajectory files

---

## 2. Design Principles

Taken directly from Terminus:

* **One tool: the terminal.** All interaction flows through tmux keystrokes. No file read tools, no bash tools, no websearch tools. The agent types what a human would type.
* **Planner outside the runtime.** The planner (Claude Code) never executes anything. It returns structured decisions. The orchestrator executes them.
* **Single pane.** One tmux session, one window, one pane per run.
* **Resilient parsing.** Malformed planner output does not crash the loop. Parse errors are fed back as the next prompt.
* **Summarization is core, not optional.** Long runs require context compression. Three-subagent summarization pipeline from the start.
* **Keystroke-only action model.** No action type abstraction. Commands are `keystrokes` + `duration`. This is the Terminus model.

---

## 3. System Context

```
┌─────────────────────────────────────────────┐
│                  Operator                    │
│         python -m termiclaw run "..."        │
│         tmux attach -t termiclaw-xxxx        │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Termiclaw Agent                 │
│                                              │
│  ┌──────────┐  ┌─────────┐  ┌────────────┐ │
│  │  Planner  │  │  Agent   │  │ Summarizer │ │
│  │ claude -p │  │  Loop    │  │ claude -p  │ │
│  └──────────┘  └─────────┘  └────────────┘ │
│                      │                       │
│               ┌──────▼──────┐               │
│               │  tmux Layer  │               │
│               │  subprocess  │               │
│               └──────┬──────┘               │
└──────────────────────┼──────────────────────┘
                       │
┌──────────────────────▼──────────────────────┐
│              tmux session                    │
│         termiclaw-<run_id_short>             │
│  ┌────────────────────────────────────────┐ │
│  │  single pane: bash --login             │ │
│  │  160 x 40, history-limit 10000000     │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## 4. Agent Loop

Direct translation of Terminus `_run_agent_loop`:

```python
for episode in range(max_turns):           # default: 1_000_000
    if not tmux.is_session_alive(session):
        break

    check_proactive_summarization()

    response = query_planner(prompt)        # claude -p, retry up to 3x
    parsed = parse_response(response)       # JSON parse with auto-fix

    if parsed.error:
        prompt = f"Previous response had parsing errors:\n{parsed.error}\n\nPlease fix these issues and respond again."
        log_step(observation=prompt, action=None, error=parsed.error)
        continue

    if parsed.task_complete:
        if pending_completion:
            log_step(observation=prompt, action=None, task_complete=True)
            break                           # confirmed completion
        else:
            pending_completion = True
            prompt = "Are you sure you want to mark the task as complete? Please review the terminal state carefully."
            log_step(observation=prompt, action=None, pending_finish=True)
            continue

    pending_completion = False

    for command in parsed.commands:
        tmux.send_keys(session, command.keystrokes)
        time.sleep(min(command.duration, 60.0))

    time.sleep(0.1)                         # 100ms minimum delay

    output = tmux.get_incremental_output(session)
    prompt = output
    log_step(observation=output, action=parsed, reasoning=parsed.analysis)
```

### Loop invariants

* Exactly one planner call per episode (except retries)
* Commands execute sequentially within a single episode
* Duration per command capped at 60 seconds
* 100ms minimum delay between planner calls
* Parse failures loop back without executing anything
* Double-finish confirmation required

---

## 5. Planner Specification

### 5.1 Invocation

```bash
claude -p \
  --output-format json \
  --max-turns 1 \
  --allowedTools "" \
  "<prompt>"
```

Flags:
* `--output-format json` — CLI wraps response in `{"type":"result","result":"...","session_id":"..."}`
* `--max-turns 1` — prevents Claude from entering its own agentic loop
* `--allowedTools ""` — disables all built-in tools (Bash, Read, Edit, etc.)

If `--allowedTools ""` is not supported, the system prompt must instruct Claude to never use tools and only return the specified JSON format.

Each call is **stateless**. No `--resume`. The prompt contains everything the planner needs: task, summary, terminal state.

### 5.2 Prompt Template

Mirroring Terminus `templates/terminus-json-plain.txt`:

```
You are a terminal agent. You interact with a Linux/macOS terminal
through a tmux session. You can only send keystrokes — you have no
other tools.

Your task:
{instruction}

{summary_section}

Current terminal state:
{terminal_state}

Respond with a JSON object containing:

1. "analysis": Brief analysis of the current terminal state and
   what has happened since your last action.

2. "plan": Your plan for the next step(s) to accomplish the task.

3. "commands": An array of commands to execute. Each command is an
   object with:
   - "keystrokes": The exact text/keys to send to the terminal.
     Include \n for Enter. Use tmux key names for special keys
     (C-c, C-d, Up, Down, etc.) as separate commands.
   - "duration": How long to wait (in seconds) after sending
     this command before capturing output.
     Guidelines: 0.1 for simple commands (ls, cat, echo),
     0.5 for moderate commands (grep, find),
     1.0-5.0 for compilation or installation,
     10.0-30.0 for long-running tasks.
     Never exceed 60 seconds.

4. "task_complete": Set to true ONLY when you are confident the
   task is fully completed. You will be asked to confirm.

Respond ONLY with the JSON object. No markdown, no explanation
outside the JSON.

Example response:
{"analysis": "The shell is at a bash prompt. No commands have been run yet.", "plan": "First, I'll check the project structure to understand the codebase.", "commands": [{"keystrokes": "ls -la\n", "duration": 0.5}], "task_complete": false}
```

### 5.3 Summary section

When a summary checkpoint exists, inserted as:

```
Summary of progress so far:
{summary_text}

Additional context (Q&A from prior summarization):
{qa_text}
```

When no summary exists, this section is omitted.

### 5.4 Terminal state format

Mirroring Terminus output prefixing:

* After an action: `"New Terminal Output:\n{incremental_output}"`
* On capture failure or first step: `"Current Terminal Screen:\n{visible_screen}"`

### 5.5 Response parsing

```python
def parse_response(raw_stdout: str) -> ParseResult:
    # Layer 1: unwrap claude -p JSON envelope
    envelope = json.loads(raw_stdout)
    text = envelope["result"]

    # Layer 2: parse Claude's response as JSON
    # Auto-fix strategies (from Terminus):
    #   - strip markdown code fences (```json ... ```)
    #   - add missing closing braces
    #   - extract JSON from mixed text (scan for first { to last })
    #   - field order validation (warn if analysis/plan/commands out of order)
    obj = try_parse_json(text)

    if obj is None:
        return ParseResult(error=f"Failed to parse JSON: {text[:500]}")

    commands = []
    for cmd in obj.get("commands", []):
        keystrokes = cmd.get("keystrokes", "")
        duration = min(float(cmd.get("duration", 0.5)), 60.0)
        commands.append(ParsedCommand(keystrokes=keystrokes, duration=duration))

    return ParseResult(
        analysis=obj.get("analysis", ""),
        plan=obj.get("plan", ""),
        commands=commands,
        task_complete=obj.get("task_complete", False),
        error=None,
    )
```

### 5.6 Retry policy

The `query_planner` function retries up to 3 times on any exception. Mirroring Terminus's tenacity decorator:

```python
def query_planner(prompt: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["claude", "-p", "--output-format", "json",
                 "--max-turns", "1", "--allowedTools", ""],
                input=prompt, capture_output=True, text=True, timeout=300
            )
            return result.stdout
        except Exception:
            if attempt == max_retries - 1:
                raise
    raise RuntimeError("unreachable")
```

---

## 6. tmux Layer

### 6.1 Session provisioning

```bash
tmux new-session -d -s termiclaw-{run_id_short} -x 160 -y 40 \
  'bash --login'
tmux set-option -t termiclaw-{run_id_short} history-limit 10000000
```

Pane defaults (matching Terminus):

| Parameter | Value |
|-----------|-------|
| Width | 160 columns |
| Height | 40 rows |
| History limit | 10,000,000 lines |
| Shell | `bash --login` |

### 6.2 Session lifecycle

* Created at run start
* Named `termiclaw-{run_id_short}` (first 8 chars of UUID)
* Operator can attach: `tmux attach -t termiclaw-{run_id_short}`
* Destroyed on run completion (configurable: keep for inspection)

### 6.3 Liveness check

```bash
tmux has-session -t {session_name}
```

Exit code 0 = alive. Non-zero = dead. Checked every episode.

### 6.4 Sending keystrokes

```bash
tmux send-keys -t {session_name} {escaped_keys}
```

* Keys are shell-escaped via `shlex.quote()`
* **16KB command length limit** — oversized input split across multiple `send-keys` calls using binary search for optimal chunk size (matching Terminus `_split_key_for_tmux`)
* Special keys (`C-c`, `C-d`, `Enter`, `Up`, `Down`) sent as separate `send-keys` invocations using tmux's native key name support
* Enter keys recognized: `Enter`, `C-m`, `KPEnter`, `C-j`

### 6.5 Output capture

**Visible screen:**
```bash
tmux capture-pane -p -t {session_name}
```

**Full scrollback:**
```bash
tmux capture-pane -p -t {session_name} -S -
```

### 6.6 Incremental output

Mirroring Terminus `get_incremental_output`:

```python
def get_incremental_output(session_name: str) -> str:
    current = capture_full_history(session_name)
    if previous_buffer and current.startswith(previous_buffer):
        incremental = current[len(previous_buffer):]
        previous_buffer = current
        if incremental.strip():
            return f"New Terminal Output:\n{incremental}"
    previous_buffer = current
    visible = capture_visible(session_name)
    return f"Current Terminal Screen:\n{visible}"
```

Diff against `previous_buffer`. If diffing fails, fall back to visible screen.

### 6.7 Output truncation

Matching Terminus `_limit_output_length`:

* Maximum output size: **10,000 bytes** (10KB)
* When exceeded: keep first 5KB + `"\n\n... [truncated] ...\n\n"` + last 5KB
* Applied before sending to planner

---

## 7. Summarization

### 7.1 Trigger

Proactive summarization when estimated prompt size approaches context limits.

Since we don't have direct token counts (Claude Code doesn't expose them in the same way), use **character count as proxy**. Trigger when total prompt length exceeds a configurable threshold (default: 100,000 characters, roughly ~25k tokens).

Fallback: also trigger on any planner call failure that suggests context overflow.

### 7.2 Three-subagent pipeline

Mirroring Terminus exactly:

**Subagent 1 — Summary generation:**

```python
prompt_1 = f"""Summarize the following agent interaction comprehensively.
Cover: major actions taken, important information discovered,
challenging problems encountered, current status.

Task: {instruction}

Interaction history:
{recent_steps_text}
"""
summary = query_planner(prompt_1)
```

**Subagent 2 — Question asking:**

```python
prompt_2 = f"""Given this task and summary, generate at least 5 questions
about critical information that might be missing from the summary.

Task: {instruction}

Summary: {summary}

Current terminal screen: {visible_screen}
"""
questions = query_planner(prompt_2)
```

**Subagent 3 — Answer providing:**

```python
prompt_3 = f"""Answer each of these questions in detail based on the
interaction history.

Questions: {questions}

Interaction history:
{full_steps_text}

Summary: {summary}
"""
answers = query_planner(prompt_3)
```

### 7.3 Context replacement

After summarization, the agent continues with:
* System prompt (unchanged)
* Task instruction (unchanged)
* Summary text (from subagent 1)
* Q&A (questions from subagent 2, answers from subagent 3)
* Current terminal state (fresh capture)

All prior step history is discarded.

### 7.4 Fallback chain

On context overflow error:

1. Full three-subagent summarization
2. Short summary — single `claude -p` call with last 1000 chars of terminal
3. Ultimate fallback — just the original instruction + last 1000 chars, no LLM call

---

## 8. Trajectory Logging

### 8.1 Format

ATIF-style JSONL. One line per step. File location: `./termiclaw_runs/{run_id}/trajectory.jsonl`

### 8.2 Step schema

```json
{
  "step_id": "uuid",
  "timestamp": "2026-04-05T12:00:00Z",
  "source": "agent",
  "message": "analysis text from planner",
  "tool_calls": [
    {
      "tool_call_id": "uuid",
      "function_name": "bash_command",
      "arguments": {
        "keystrokes": "pytest test_auth.py\n",
        "duration": 2.0
      }
    }
  ],
  "observation": {
    "terminal_output": "New Terminal Output:\n...",
    "truncated": false
  },
  "metrics": {
    "prompt_chars": 15000,
    "response_chars": 500,
    "duration_ms": 3200
  },
  "is_copied_context": false,
  "error": null
}
```

Task completion logged as:
```json
{
  "tool_calls": [
    {"function_name": "mark_task_complete", "arguments": {}}
  ]
}
```

Summarization steps logged with `"source": "system"` and a reference to the summary checkpoint.

### 8.3 Run metadata

Written to `./termiclaw_runs/{run_id}/run.json`:

```json
{
  "run_id": "uuid",
  "instruction": "fix the failing test",
  "started_at": "2026-04-05T12:00:00Z",
  "finished_at": "2026-04-05T12:05:00Z",
  "status": "succeeded",
  "total_steps": 15,
  "tmux_session": "termiclaw-a1b2c3d4",
  "termination_reason": "task_complete_confirmed"
}
```

---

## 9. Data Model

All types are stdlib `dataclasses` with no external dependencies.

```python
@dataclass(frozen=True)
class ParsedCommand:
    keystrokes: str
    duration: float

@dataclass(frozen=True)
class ParseResult:
    analysis: str = ""
    plan: str = ""
    commands: list[ParsedCommand] = field(default_factory=list)
    task_complete: bool = False
    error: str | None = None
    warning: str | None = None

@dataclass
class RunState:
    run_id: str
    instruction: str
    tmux_session: str
    started_at: str
    status: str                              # pending, active, succeeded, failed, cancelled
    current_step: int
    max_turns: int
    pending_completion: bool
    previous_buffer: str                     # last full capture for incremental diff
    summary: str | None                      # latest summary checkpoint
    qa_context: str | None                   # latest Q&A from summarization
    total_prompt_chars: int                  # running total for summarization trigger

@dataclass(frozen=True)
class StepRecord:
    step_id: str
    timestamp: str
    source: str                              # "agent", "system", "error"
    observation: str
    analysis: str | None
    plan: str | None
    commands: list[ParsedCommand]
    task_complete: bool
    error: str | None
    metrics: dict
    is_copied_context: bool
```

---

## 10. Configuration

No config file for MVP. All configuration via CLI args with Terminus-matching defaults.

```python
@dataclass(frozen=True)
class Config:
    instruction: str                         # the task
    max_turns: int = 1_000_000               # Terminus default
    pane_width: int = 160                    # Terminus default
    pane_height: int = 40                    # Terminus default
    history_limit: int = 10_000_000          # Terminus default
    max_output_bytes: int = 10_000           # Terminus default (10KB)
    max_command_length: int = 16_000         # Terminus default (16KB)
    max_duration: float = 60.0               # Terminus cap
    min_delay: float = 0.1                   # 100ms between calls
    planner_timeout: int = 300               # 5 min subprocess timeout
    planner_retries: int = 3                 # Terminus default
    summarization_threshold: int = 100_000   # chars (~25k tokens)
    keep_session: bool = False               # keep tmux after completion
    runs_dir: str = "./termiclaw_runs"       # trajectory output
```

---

## 11. CLI

```
termiclaw run "fix the failing test in test_auth.py"
termiclaw run --task task.txt --max-turns 50 --keep-session --verbose
termiclaw attach <run-id>
termiclaw list [--runs-dir DIR]
termiclaw show <run-id> [--runs-dir DIR]
termiclaw status
```

### `run`

1. Validate tmux is installed (`tmux -V`)
2. Validate `claude` is installed and authenticated (`claude --version`)
3. Generate run ID (`uuid4`)
4. Create run directory
5. Provision tmux session
6. Enter agent loop
7. On exit: write `run.json`, optionally destroy tmux session

### `attach`

Prefix-matches run ID against active tmux sessions, attaches if unique match.

### `list`

Table of all runs: ID, status, steps, prompt chars, duration, instruction.

### `show`

Prints run metadata and step-by-step trajectory with commands and errors.

### `status`

Checks Claude Code quota via `claude -p`.

---

## 12. Error Handling

Mirroring Terminus:

| Error | Behavior |
|-------|----------|
| JSON parse failure | Send error text back as next prompt, continue loop |
| `claude -p` subprocess failure | Retry up to 3 times, then send error as prompt |
| `claude -p` timeout (>5 min) | Treat as failure, retry |
| tmux session died | Exit loop, mark run as failed |
| tmux send-keys failure | Log error, send error as next observation |
| Context overflow from planner | Trigger summarization fallback chain |
| Keyboard interrupt (Ctrl-C) | Graceful shutdown: log final state, write `run.json`, keep tmux session |

No hard cap on consecutive parse failures. The loop continues until `max_turns` or session death — matching Terminus behavior.

---

## 13. Project Structure

```
termiclaw/
  __init__.py       # package marker
  cli.py            # argparse: run, attach, list, show, status
  agent.py          # main observe-decide-act loop
  planner.py        # claude -p invocation, response parsing, auto-fix
  tmux.py           # tmux subprocess wrapper (provision, send, capture)
  models.py         # dataclasses (Config, RunState, RunInfo, ParseResult, etc.)
  summarizer.py     # three-subagent summarization pipeline
  trajectory.py     # JSONL logging, run listing, trajectory reading
  logging.py        # JSON-lines structured logger
scripts/
  check-branch.sh   # pre-commit: block main, require rebase
tests/
  unit/             # domain logic, parsing, truncation, CLI
  integration/      # tmux operations against real tmux
```

Zero runtime dependencies. Python 3.13+ stdlib only.
Entry point: `termiclaw = "termiclaw.cli:main"` via `pyproject.toml`.

---

## 14. Non-Functional Requirements

### 14.1 Packaging

* `uv` as package manager
* `pyproject.toml` with `hatchling` build backend
* `uv.lock` committed to version control
* Dependency groups: `test`, `lint`, `typecheck`, `dev` (includes all)
* Zero runtime dependencies — only dev/test tooling is external

### 14.2 Type checking

* `ty` (Astral's type checker) with strict settings
* No use of `Any`, `object` as escape hatches, `cast`, or `type: ignore`
* All functions fully annotated with return types
* Domain objects as typed `dataclasses` with specific field types
* All `dict` types must be typed (e.g., `dict[str, int]`, not bare `dict`)

### 14.3 Linting and formatting

* `ruff` as both linter and formatter
* Comprehensive rule set: annotations, bugbear, security, complexity, pathlib, pytest style
* No rule exceptions — code must satisfy all enabled rules
* Max complexity: 10 (mccabe)

### 14.4 Testing

* `pytest` with `pytest-cov`
* Testing pyramid: unit > integration > end-to-end
* Coverage > 84% enforced in CI
* Branch coverage enabled
* Unit tests: domain logic, parsing, truncation, policies (no subprocess, no tmux)
* Integration tests: tmux operations against real tmux
* End-to-end: scripted planner with real agent loop

### 14.5 All dependencies up to date

* Dev dependencies pinned to latest stable versions
* `uv lock` regenerated when versions are bumped
* No version warnings, no deprecation warnings

---

## 15. Observability

### 15.1 Structured logging

All log output is JSONL to stderr. Uses stdlib `logging` with a custom JSON formatter.

Every log line includes:

```json
{"ts": "2026-04-05T12:00:00.123Z", "level": "INFO", "run_id": "abc123", "step": 3, "component": "planner", "event": "query_sent", "msg": "Sending planner request", "prompt_chars": 15000}
```

Required fields: `ts`, `level`, `run_id`, `component`, `event`, `msg`.
Optional fields vary by component (e.g., `step`, `prompt_chars`, `duration_ms`, `exit_code`).

Components: `agent`, `planner`, `tmux`, `summarizer`, `trajectory`, `cli`.

Log levels:
* `DEBUG` — raw planner output, full capture text
* `INFO` — step start/end, action executed, summarization triggered
* `WARNING` — parse failure recovered, retry attempt
* `ERROR` — tmux session died, planner subprocess failed

No `print()` statements anywhere — all output through the logger.

---

## 16. Startup Checks

Before entering the agent loop:

1. `tmux -V` — verify tmux is installed. If not: print install instructions and exit.
2. `claude --version` — verify Claude Code is installed. If not: print install instructions and exit.
3. Verify no existing tmux session with the same name (collision avoidance).
4. Create `runs_dir` if it doesn't exist.

---

## 17. Differences from Terminus

| Aspect | Terminus | Termiclaw |
|--------|----------|-----------|
| LLM backend | LiteLLM (direct API) | `claude -p` (CLI subprocess) |
| Context management | In-process chat history | Stateless calls, context rebuilt each step |
| Authentication | API key | Claude Code subscription (OAuth) |
| Execution environment | Docker container | Local tmux session |
| Async | asyncio | Synchronous |
| Dependencies | litellm, pydantic, tenacity, etc. | None (stdlib only) |
| Response parsing | JSON or XML parsers | JSON parser only |
| Session continuity | LLM sees full chat | LLM sees task + summary + current state |
| Token tracking | Direct from API response | Character count proxy |

---

## 18. Implementation Order

### Phase 1: Core skeleton

* `models.py` — all dataclasses
* `tmux.py` — provision, send-keys, capture-pane, incremental output, session destroy
* `trajectory.py` — JSONL append, run metadata write

### Phase 2: Planner

* `planner.py` — `claude -p` invocation, JSON envelope unwrap, response parser with auto-fix, retry logic

### Phase 3: Agent loop

* `agent.py` — full observe-decide-act loop, double-finish confirmation, error feedback

### Phase 4: Summarization

* `summarizer.py` — three-subagent pipeline, fallback chain, context replacement

### Phase 5: CLI

* `cli.py` — argparse for `run` and `attach`
* `__main__.py` — entry point

### Phase 6: Hardening

* Startup checks
* Graceful shutdown on Ctrl-C
* Edge cases (empty output, huge output, tmux death mid-step)

---

## 19. Acceptance Criteria

The implementation is complete when:

* `python -m termiclaw run "create a file called hello.txt with 'hello world' in it"` successfully creates the file via tmux keystrokes
* The operator can `tmux attach` during the run and watch commands being typed
* The trajectory JSONL contains every step with observations and actions
* Parse errors from the planner are recovered from without crashing
* A long-running task triggers summarization and continues successfully
* Double-finish confirmation prevents premature completion
* Ctrl-C during a run writes final state and keeps the tmux session
* The entire project is stdlib-only Python 3.13
* All code passes `ruff check`, `ruff format --check`, and `ty check` with zero warnings
* Test coverage exceeds 90% with branch coverage
* All logging is structured JSONL to stderr — no `print()` anywhere
* No use of `Any`, `cast`, or `type: ignore` in the codebase

---

## 20. Evals, Benchmarking, and Autoresearch

### 20.1 Terminal-Bench

[Terminal-Bench](https://www.tbench.ai/) (tbench.ai) is the primary benchmark for terminal agents. Version 2.0 has 89 tasks across software engineering, biology, security, and gaming. Each task runs in a Docker container with automated verification tests.

Key design decisions relevant to Termiclaw:

- **Time-based limits** (not turn-based) — turn limits penalize agents that monitor long-running processes, which is exactly what terminal agents need to do well. Termiclaw's duration-based waiting aligns with this.
- **Scaffolding matters** — the same model scores 2-6 points differently depending on the agent wrapping it. Agent architecture (prompt engineering, summarization, error recovery) is measurable.
- **ATIF trajectories** — Terminal-Bench uses the [Agent Trajectory Interchange Format](https://github.com/laude-institute/harbor/blob/main/docs/rfcs/0001-trajectory-format.md) for logging. Termiclaw already writes ATIF-compatible JSONL.

Source: [tbench.ai/leaderboard/terminal-bench/2.0](https://www.tbench.ai/leaderboard/terminal-bench/2.0), [arxiv 2601.11868](https://arxiv.org/html/2601.11868v1)

### 20.2 Karpathy's AutoResearch

[AutoResearch](https://github.com/karpathy/autoresearch) (21k+ stars) runs ML experiments in an autonomous loop: an AI agent reads code, forms a hypothesis, modifies the code, runs the experiment under a fixed compute budget, and evaluates results. Only changes that beat the current best metric are kept.

> "You are not touching any of the Python files like you normally would as a researcher. Instead, you are programming the program.md Markdown files that provide context to the AI agents." — [Karpathy](https://github.com/karpathy/autoresearch)

The pattern applies directly to Termiclaw's eval-driven improvement:

1. Define a `program.md` describing what to optimize (prompt template, summarization strategy, error recovery)
2. Run Termiclaw against a task set (Terminal-Bench subset or custom tasks)
3. Measure pass rate, token usage, cost, step count
4. Keep only changes that improve metrics
5. Repeat

Source: [github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch), [VentureBeat](https://venturebeat.com/technology/andrej-karpathys-new-open-source-autoresearch-lets-you-run-hundreds-of-ai)

### 20.3 Agent harness architecture

An **agent harness** is the infrastructure layer that:
- Provisions the execution environment (Docker container, tmux session)
- Feeds the task description to the agent
- Captures trajectories in a standard format (ATIF)
- Runs verification tests after agent completion
- Reports pass/fail with metrics

Terminal-Bench, [SWE-bench](https://www.swebench.com/SWE-bench/), and similar benchmarks all use this pattern. The harness is separate from the agent — the same harness can evaluate different agents on the same tasks.

Termiclaw's architecture maps to this directly:
- `tmux.provision_session()` = environment provisioning
- `agent.run()` = agent execution
- `trajectory.append_step()` = trajectory capture
- A missing piece: **automated verification** (the `VerifierSpec` from the original PLAN.md)

Source: [Terminal-Bench Dataset Registry](https://www.tbench.ai/news/registry-and-adapters), [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent/)

### 20.4 Eval-driven improvement strategy

> "Final response evaluation tells you *what* went wrong. Trajectory evaluation tells you *where* it went wrong. Single step evaluation tells you *why* it went wrong." — [Anthropic, Demystifying Evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

Concrete strategies for Termiclaw:

**Failure categorization.** Tag every failed run with a root cause: `premature_completion`, `parse_failure`, `wrong_command`, `stuck_loop`, `timeout`, `hallucination`. The SQLite DB makes this queryable.

**Prompt tuning via error patterns.** Quantify failure categories across runs. If 15% of failures are premature completion, strengthen the double-confirmation prompt. If 10% are parse failures, improve the auto-fix pipeline. Measure the effect.

**A/B testing prompts.** Run the same task set with prompt variant A vs B. The 2-6 point scaffolding delta on Terminal-Bench shows these changes are measurable.

**Trajectory analysis.** Use ATIF logs to find the exact step where reasoning diverged. Compare successful vs failed runs on the same task to identify the decision point.

**Iterative refinement loop.** The autoresearch pattern: modify prompt/architecture → run evals → keep improvements → repeat. This is systematic, not ad-hoc.

Source: [Anthropic evals guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), [LangChain trajectory evals](https://docs.langchain.com/langsmith/trajectory-evals)

### 20.5 Roadmap for Termiclaw evals

**Phase 1: Task runner.** Add a `termiclaw eval` command that runs a directory of task files, captures pass/fail via exit code or output matching, and reports aggregate results.

**Phase 2: Terminal-Bench compatibility.** Implement the Terminal-Bench harness adapter so Termiclaw can be evaluated on the official benchmark. This requires Docker containerization and ATIF trajectory export (already partially done).

**Phase 3: Autoresearch loop.** Create a `program.md` describing Termiclaw's optimization surface (prompt template, summarization triggers, error recovery). Use the autoresearch pattern to systematically improve pass rates on a task set.

**Phase 4: Failure analysis dashboard.** Query the SQLite DB to categorize failures, track improvement over time, and identify the highest-leverage changes.

### 20.6 Required features for eval support

The following features are needed in Termiclaw to fully support evals and autoresearch. Items marked with `[MVP]` are required for Phase 1.

#### Task verification `[MVP]`

Tasks need a machine-checkable success condition. Add a `VerifierSpec` to the task definition:

```toml
# task.toml
instruction = "Create hello.txt with 'hello world'"

[verifier]
command = "cat hello.txt"
expected_output = "hello world"
timeout_seconds = 10
```

The verifier runs after the agent signals completion. Exit code 0 + output match = pass. This replaces the current "trust the LLM's self-assessment" approach.

#### `termiclaw eval` command `[MVP]`

```bash
termiclaw eval tasks/           # run all .toml files in directory
termiclaw eval tasks/ --repeat 3  # run each task 3 times for statistical significance
termiclaw eval tasks/ --model sonnet  # override planner model
termiclaw eval tasks/ --parallel 4    # run 4 tasks concurrently
```

Outputs a results table:

```
TASK                    PASS  FAIL  RATE   AVG STEPS  AVG COST
create-file             3/3   0/3   100%   2.0        $0.02
fix-test                2/3   1/3   67%    5.3        $0.08
multi-step-project      1/3   2/3   33%    12.0       $0.15
TOTAL                   6/9   3/9   67%
```

Results stored in SQLite DB alongside run data.

#### Docker isolation

Terminal-Bench runs tasks in Docker containers. Termiclaw needs:

```bash
termiclaw eval tasks/ --docker          # run each task in a fresh container
termiclaw eval tasks/ --docker-image ubuntu:24.04
```

The Docker adapter replaces `tmux.provision_session()` with container creation + tmux inside the container. This ensures tasks can't interfere with each other or the host.

#### Prompt variants and A/B testing

```bash
termiclaw eval tasks/ --prompt-file prompts/v2.txt   # test alternate prompt
termiclaw eval tasks/ --prompt-file prompts/v1.txt prompts/v2.txt  # A/B compare
```

The eval command runs the same tasks with each prompt variant and reports comparative results. Prompt templates become first-class configurable artifacts, not hardcoded strings.

#### ATIF export `[MVP]`

```bash
termiclaw export <run-id> --format atif    # export a single run
termiclaw export --all --format atif       # export all runs
```

Produces ATIF-v1.6 compatible JSON for submission to Terminal-Bench or for SFT/RL training pipelines. The current trajectory.jsonl is close but needs: `schema_version`, `session_id` wrapper, `model_name` per step, `reasoning_content` field.

#### Failure tagging `[MVP]`

```bash
termiclaw tag <run-id> --failure premature_completion
termiclaw tag <run-id> --failure wrong_command --step 5
termiclaw failures                  # show failure category breakdown
termiclaw failures --since 7d       # last 7 days
```

Tags stored in SQLite. Enables the failure categorization strategy from section 20.4.

#### Autoresearch integration

A `program.md` file describes the optimization surface:

```markdown
# Termiclaw Optimization

## What to optimize
- Prompt template (`termiclaw/planner.py:_PROMPT_TEMPLATE`)
- Summarization threshold (`Config.summarization_threshold`)
- Duration estimation guidance in prompt
- Error recovery prompt text

## Eval command
termiclaw eval tasks/benchmark/ --repeat 3

## Metric
Pass rate on task set (higher is better)

## Budget
Each experiment: max 10 tasks, max $5 API cost
```

The autoresearch loop: read `program.md` → form hypothesis → modify code → run eval → compare to baseline → keep or discard. This can be driven by Claude Code itself or by a separate orchestrator.

#### Model routing

The [OpenDev paper](https://arxiv.org/abs/2603.05344) shows that workload-specialized model routing improves both performance and cost. For Termiclaw:

- Use a fast/cheap model (Haiku, Sonnet) for simple observations (shell idle, command completed)
- Use a capable model (Opus) for complex reasoning (debugging, multi-step planning)
- Route based on observation complexity (output length, error presence, step count)

```bash
termiclaw run "fix the bug" --model-router auto   # adaptive routing
termiclaw run "fix the bug" --model opus           # force specific model
```

#### Metrics collection

The SQLite DB already tracks tokens and cost. Additional metrics needed for eval analysis:

- **Time to first action**: how long before the agent sends its first command
- **Observation-to-action ratio**: are observations being wasted on no-ops?
- **Backtrack count**: how many times did the agent undo or retry an approach?
- **Verifier calls**: how many verification attempts before success?
- **Context utilization**: what fraction of the prompt is actual content vs template?
