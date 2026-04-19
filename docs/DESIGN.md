# Termiclaw vs. Terminus: Design Comparison

This document compares Termiclaw's design against its two ancestors:

- **Terminus (1)** — the research-preview agent described in the [tbench.ai announcement](https://www.tbench.ai/news/terminus). The design principles.
- **Terminus-2** — the Harbor Framework reference implementation (`harbor-framework/harbor`, `src/harbor/agents/terminus_2/`). The concrete source read by the Termiclaw authors, analyzed in [TERMINUS.md](../TERMINUS.md).

Termiclaw inherits the *principles* from Terminus-1 and the *loop shape and parameters* from Terminus-2, then adapts both for a subscription-authenticated Claude Code backend running in a Docker container.

---

## 1. Lineage at a glance

| Principle (Terminus-1)                      | Concrete mechanism (Terminus-2)                            | Termiclaw                                                  |
|---------------------------------------------|-------------------------------------------------------------|-------------------------------------------------------------|
| "A single tool: an interactive tmux session" | `TmuxSession` wrapper, raw `send-keys`                      | `termiclaw/container.py`, raw `send-keys` inside a Docker container |
| "Will never ask for user input"             | No user-input tool; agent must self-unblock                 | No user-input tool; double-confirm instead of early exit    |
| "Lives outside the environment"             | Python process ↔ dockerized env via `environment.exec()`    | Python process → Docker container with tmux inside          |
| Model-agnostic                              | LiteLLM / Tinker; pluggable backends                        | Claude Code only (`claude -p` subprocess)                   |
| Autonomous loop                             | `for episode in range(max_episodes)` with chat history      | `decide(state, event) → apply(cmd, ports) → event` with **stateless** planner calls |

Terminus-1 fixed the *philosophy*; Terminus-2 fixed the *parameters*; Termiclaw fixed the *packaging* (zero-dependency, stdlib-only, single binary entrypoint).

---

## 2. Architecture

### Terminus-2

```
┌────────────────────────┐       ┌──────────────────────────┐
│  Terminus2 agent       │       │  Docker container        │
│  (Python, LiteLLM)     │◀─────▶│  tmux session            │
│  in-process chat hist. │ exec  │  bash --login            │
└────────────────────────┘       └──────────────────────────┘
   ↑
   │ provider API (HTTP)
   ▼
 (Anthropic / OpenAI / local)
```

- Agent and env are decoupled: the agent survives broken dependencies or minimal resources in the target container.
- Chat history lives in-process; the LLM is hit directly over HTTP.

### Termiclaw

```
┌────────────────────────┐       ┌──────────────────────────┐
│  Termiclaw agent       │       │  Docker container        │
│  (Python, stdlib only) │◀─────▶│  tmux + bash --login     │
│  pure decide + ports   │ exec  │  (ubuntu:24.04 base)     │
└──────┬─────────────────┘       └──────────────────────────┘
       │ subprocess
       ▼
  claude -p --output-format json --max-turns 1 --allowedTools ""
       ▼
  Anthropic API (OAuth via Claude Code subscription)
```

- The agent runs on the host; the terminal lives inside a Docker container started per run (content-hashed `termiclaw-base:<sha256[:12]>` image built from the repo `Dockerfile`).
- The planner is reached via a CLI subprocess, not a library. Authentication is the user's Claude Code subscription, not an API key.
- Every planner call is stateless; the agent rebuilds the whole prompt each turn.
- Internally the loop is `decide(state, event) → apply(cmd, ports) → event` — pure decision core + imperative shell over typed `Ports` Protocols. See `termiclaw/decide.py` and `termiclaw/shell.py`.

---

## 3. The reasoning loop

All three agents run the same **observe → decide → act** shape:

```
for episode in range(max_turns):
    observe()          # capture terminal
    decide()           # query LLM
    if task_complete:  # double-confirm, then break
        ...
    act()              # send keystrokes
```

What changes between them is what `decide()` is allowed to remember.

| Aspect                           | Terminus-1 (principle)   | Terminus-2                              | Termiclaw                                                 |
|----------------------------------|---------------------------|-----------------------------------------|------------------------------------------------------------|
| Loop entry                       | `run()`                   | `_run_agent_loop()`                     | `agent.run()` → `decide()` + `apply()` loop in `agent.py` / `decide.py` / `shell.py` |
| Max iterations                   | Unspecified               | `1_000_000`                             | `1_000_000` (Config.max_turns)                             |
| Completion confirmation          | Implicit                  | Double-finish (`_pending_completion`)   | Double-finish (`State.pending_completion`)                 |
| Per-call retries                 | N/A                       | `tenacity` decorator, 3 attempts        | Inline loop over `TimeoutExpired`/non-zero exit, 3 tries   |
| Min inter-step delay             | Unspecified               | None explicit                           | `100ms` (`Config.min_delay`)                               |
| Per-command duration cap         | Unspecified               | `60s` (enforced in `_handle_llm_…`)     | `60s` (`Config.max_duration`, enforced in planner + agent) |
| Chat memory                      | Implicit (LLM state)      | In-process chat list, unwind on overflow | **None.** Context rebuilt from instruction + summary + obs |

The critical divergence is *stateless planner calls*. Terminus-2 keeps a growing chat history and compresses it when it nears the context window. Termiclaw builds a fresh prompt every turn:

```
[instruction] + [summary? + Q&A?] + [current terminal state]
```

This gives termiclaw two properties for free:

1. No token-accounting bugs from multi-turn histories.
2. `claude -p` can be replaced with any stateless JSON-in/JSON-out subprocess.

The cost is that the LLM sees no prior analysis/plan unless summarization has already fired — the "last N turns" context that Terminus-2 keeps implicit must be manufactured by summarization.

---

## 4. Action model

All three use the same narrow interface: **keystrokes + duration**. There is no `write_file`, no `run_bash`, no `read_file`. The agent types what a human would type.

Terminus-1, verbatim:

> "Terminus has only a single tool at its disposal: an interactive tmux session running inside its execution environment."

> "Terminus will never ask for user input and will instead independently push to complete its task on its own to the best of its ability."

Termiclaw's planner prompt is a direct descendant (`termiclaw/planner.py:13-58`):

```
You are a terminal agent. You interact with a Linux/macOS terminal
through a tmux session. You can only send keystrokes — you have no
other tools.
```

Response schema (all three):

```json
{
  "analysis": "...",
  "plan": "...",
  "commands": [{"keystrokes": "ls -la\n", "duration": 0.5}],
  "task_complete": false
}
```

| Aspect                          | Terminus-2                                   | Termiclaw                                                |
|---------------------------------|----------------------------------------------|----------------------------------------------------------|
| Response formats accepted       | JSON *or* XML (`parser_name` config)         | JSON only (single parser)                                |
| Tool-use API                    | Never. Plain-text JSON/XML in assistant msg  | Never. Plain-text JSON in `claude -p` result field       |
| Special keys                    | tmux native key names (`C-c`, `Enter`, etc.) | tmux native key names (`C-c`, `Enter`, `Escape`, etc.)   |
| Literal text sending            | `send-keys` with shell-quoted string         | `send-keys -l` (literal mode); regex gate for key names  |
| Keystroke splitting             | Binary-search chunking at 16KB               | Binary-search chunking (see §9 for a divergence)         |
| Blocking command wait           | Optional (`; tmux wait -S done` mode)        | Not implemented; duration-sleep only                     |
| Per-command max duration        | Capped at 60s                                | Capped at 60s                                            |

### Why no tool-use API?

This is the central design choice inherited straight from Terminus-1. Provider-specific tool-use shapes (OpenAI functions, Anthropic tool use, etc.) would tie the agent to a provider. Plain text JSON in the completion body is the lowest common denominator, and it survives model swaps, fine-tunes, and local models.

Termiclaw doubles down on this because `claude -p --output-format json` returns a `result` field that is itself a string — the planner's actual JSON is nested inside. The parser unwraps this envelope before applying the same auto-fix strategies (strip code fences, add closing braces, extract mixed content) that Terminus-2 uses.

---

## 5. Context management

### Terminus-2

- **Proactive trigger:** free tokens < `proactive_summarization_threshold` (default `8000`).
- **Reactive trigger:** `ContextLengthExceededError` from the provider.
- **Three-subagent pipeline:** summary → questions → answers. Questions subagent runs on an **empty** message history to avoid contamination. Answer subagent runs on the full unwound history.
- **Pre-summarization unwind:** `_unwind_messages_to_free_tokens` drops message pairs from the tail until 4000 tokens are free.
- **Fallback chain:** full pipeline → short single-call summary → non-LLM fallback (instruction + last 1000 chars).

### Termiclaw

Same three-subagent pipeline, same fallback chain. The differences are all shape:

| Aspect                          | Terminus-2                                     | Termiclaw                                                |
|---------------------------------|-------------------------------------------------|----------------------------------------------------------|
| Trigger metric                  | Free tokens (from provider API)                 | **Accumulated prompt tokens** (`planner.extract_usage` ground truth) |
| Threshold                       | `8000` free tokens                              | `25_000` accumulated tokens (`Config.summarization_token_threshold`) |
| Unwind strategy                 | Drop last pairs until 4000 free                 | None — all prior state is in `recent_steps` (cap 20)     |
| Subagent isolation              | Separate provider calls with crafted histories  | Separate `claude -p` calls, each stateless               |
| Context after summarization     | `[system, questions, answers]` + next obs       | Summary + Q&A injected as prompt section + next obs      |

`claude -p` returns per-call input / output / cache-read token counts in the response envelope; `planner.extract_usage` parses them and the running sum lives in `State.total_prompt_tokens`. There is no "tokens remaining in the window" notion when every call is stateless, so the trigger is *accumulated tokens sent so far*, compared against `Config.summarization_token_threshold`. This is a ground-truth metric, not a char-count proxy.

---

## 6. tmux substrate

| Parameter               | Terminus-2     | Termiclaw (Config)  | Notes                                                 |
|-------------------------|----------------|----------------------|-------------------------------------------------------|
| Pane width              | 160            | 160                  | Match                                                 |
| Pane height             | 40             | 40                   | Match                                                 |
| `history-limit`         | 10,000,000     | 10,000,000           | Match                                                 |
| Shell                   | `bash --login` | `bash --login`       | Match                                                 |
| Session naming          | `terminus_2`   | `termiclaw-<8hex>`   | One session per run vs one fixed                      |
| PTY allocation          | `script -qc …` | none (tmux directly) | Termiclaw runs tmux inside a Docker container (ubuntu:24.04); the container's tmux has its own pty |
| `pipe-pane` logging     | Optional       | None                 | Termiclaw logs via ATIF + SQLite instead              |
| Output truncation       | 10,000 bytes   | 10,000 bytes         | First 5KB + marker + last 5KB                         |
| Incremental capture     | Full-diff      | Full-diff            | Same algorithm; fallback to visible screen on failure |
| Max send-keys chunk     | 16,000 chars   | 200,000 chars        | **Divergence** — see §9                               |
| Scrollback depth read   | `-S -` (full)  | `-S -10000`          | **Divergence** — see §9                               |
| Tmux install bootstrap  | Builds 3.4 from source if missing | Requires tmux pre-installed (startup check) | Termiclaw expects a host with tmux |

---

## 7. Trajectory format and observability

Both agents produce ATIF-style step records. Termiclaw's schema (`trajectory.py:_step_to_dict`) maps cleanly to the Terminus-2 `Step` dataclass:

| Field                 | Terminus-2                      | Termiclaw                                      |
|-----------------------|----------------------------------|------------------------------------------------|
| `step_id`             | uuid                             | uuid                                           |
| `timestamp`           | UTC ISO                          | UTC ISO                                        |
| `source`              | user / agent / system            | agent / system / error                         |
| `message`             | text content                     | `analysis` field (mapped)                      |
| `reasoning_content`   | CoT if available                 | Not captured (Claude Code hides CoT)           |
| `tool_calls`          | `bash_command`, `mark_task_complete` | Same                                      |
| `observation`         | terminal output or subagent ref  | `{"terminal_output": "..."}`                   |
| `metrics`             | tokens, cost, logprobs           | tokens, cost, duration_ms, prompt_tokens, prompt_version |
| `is_copied_context`   | from summarization handoff      | from summarization handoff                     |

Where termiclaw extends Terminus-2:

- **SQLite mirror.** Every run and step is also persisted to `~/.local/state/termiclaw/log/termiclaw.db` (via `db.py`) with indexed tables for runs, steps, and commands. The JSONL file is canonical; the DB exists for fast queries. Terminus-2 only writes trajectory files.
- **Separate structured log.** JSONL to `~/Library/Logs/termiclaw/<run>.jsonl` (macOS) via `logging.py`, with components `agent|planner|tmux|summarizer|trajectory|cli`. Terminus-2 relies on Python logging defaults.

---

## 8. Configuration surface

Termiclaw's `Config` dataclass (`models.py:64`) inherits Terminus-2's defaults where they apply:

| Parameter                  | Terminus-2 default | Termiclaw default | Match |
|----------------------------|--------------------|-------------------|-------|
| `max_turns`                | 1,000,000          | 1,000,000         | ✅     |
| `pane_width`               | 160                | 160               | ✅     |
| `pane_height`              | 40                 | 40                | ✅     |
| `history_limit`            | 10,000,000         | 10,000,000        | ✅     |
| Output truncation          | 10,000             | 10,000            | ✅     |
| Max duration per cmd       | 60.0s              | 60.0s             | ✅     |
| Planner retries            | 3                  | 3                 | ✅     |
| Summarization threshold    | 8000 free tokens   | 100,000 chars     | ≈ (different units) |
| Temperature                | 0.7                | N/A (claude -p)   | –     |
| `reasoning_effort`         | configurable       | N/A               | –     |
| `interleaved_thinking`     | configurable       | N/A               | –     |
| `keep_session`             | —                  | `False`           | +     |
| `runs_dir`                 | —                  | `./termiclaw_runs`| +     |

Termiclaw has no knobs for temperature, reasoning effort, or interleaved thinking because `claude -p` does not expose them on the subscription-backed CLI.

---

## 9. Summary of differences

| Axis                     | Terminus-1 (principles) | Terminus-2 (reference)       | Termiclaw                                    |
|--------------------------|--------------------------|------------------------------|----------------------------------------------|
| LLM backend              | Any                      | LiteLLM / Tinker             | `claude -p` subprocess                        |
| Auth                     | API key                  | API key                      | Claude Code OAuth subscription               |
| Execution env            | Docker                   | Docker                       | Local host                                   |
| Dependencies             | —                        | `litellm`, `pydantic`, `tenacity`, etc. | stdlib only                           |
| Async runtime            | —                        | `asyncio`                    | Synchronous                                  |
| Response parsing         | —                        | JSON **or** XML              | JSON only                                    |
| Chat memory              | In-LLM                   | In-process chat list         | Stateless — rebuilt each call                |
| Token accounting         | Provider                 | Provider                     | `planner.extract_usage` pulls real counts from the `claude -p` envelope |
| Session continuity       | Full history             | Full history with unwinding  | Instruction + summary + observation          |
| Completion semantic      | LLM decides              | Double-finish                | Double-finish                                |
| Trajectory format        | —                        | ATIF                         | ATIF + SQLite                                |
| Target user              | Researchers              | Researchers, benchmark authors | Developers on Claude Code subscriptions    |
