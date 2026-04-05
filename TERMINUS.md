# Terminus-2 Agent: Source Code Reference

## Overview

Terminus-2 is a terminal AI agent from the Harbor Framework (`harbor-framework/harbor`), located at `src/harbor/agents/terminus_2/`. It is model-agnostic, uses tmux as its sole execution substrate, and controls terminals through raw keystrokes only.

Key files:
- `terminus_2.py` (~1800 lines) — main agent class
- `tmux_session.py` (~600 lines) — tmux wrapper
- `terminus_json_plain_parser.py` / `terminus_xml_plain_parser.py` — response parsers
- `templates/terminus-json-plain.txt` / `terminus-xml-plain.txt` — prompt templates
- `templates/timeout.txt` — timeout feedback template

---

## Core Loop

### Entry Point

Class `Terminus2(BaseAgent)`. Entry is `run()` → `_run_agent_loop()`.

### Control Flow

```python
for episode in range(self._max_episodes):  # default: 1_000_000
    if not session.is_session_alive():
        break
    _check_proactive_summarization()
    _handle_llm_interaction(chat, prompt, ...)  # calls _query_llm, parses response
    _execute_commands(parsed_commands)
    output = session.get_incremental_output()
    prompt = output  # feed observation back as next prompt
```

### Stopping: Double Confirmation

When the LLM sets `task_complete: true`:
1. Agent sets `_pending_completion = True`
2. Sends confirmation message: `"Are you sure you want to mark the task as complete?"`
3. LLM must return `task_complete: true` a second time to actually stop

This prevents premature exits.

### Error Handling

- `_query_llm` is decorated with `@retry(stop=stop_after_attempt(3))` via tenacity
- Retries on all `Exception` types **except** `ContextLengthExceededError` and `asyncio.CancelledError`
- Parse errors (invalid JSON/XML from LLM) do NOT crash the loop
- On parse failure, the error text is sent back as the next prompt:
  `"Previous response had parsing errors:\n{feedback}\n\nPlease fix these issues..."`
- No commands are executed on parse failure; the loop just continues

---

## tmux Integration (`TmuxSession`)

### Session Setup

The agent runs tmux inside the evaluation Docker container via `environment.exec()`. It first attempts to install tmux (with fallback to building tmux 3.4 from source). Session creation:

```bash
script -qc "tmux new-session -x 160 -y 40 -d -s terminus_2 \
  'bash --login' \; pipe-pane -t terminus_2 'cat > /path/to/log'" /dev/null
```

- `pipe-pane` enables optional logging of all pane output
- `script -qc` allocates a PTY

### Pane Configuration

| Parameter | Default |
|-----------|---------|
| `tmux_pane_width` | 160 |
| `tmux_pane_height` | 40 |
| `history_limit` | 10,000,000 lines |

History limit set via `tmux set-option -g history-limit 10000000`.

### Output Capture

- **Visible screen:** `tmux capture-pane -p -t {session_name}`
- **Full scrollback:** `tmux capture-pane -p -t {session_name} -S -` (with `capture_entire=True`)
- **Incremental output:** `get_incremental_output()` diffs current full buffer against `_previous_buffer`
  - If diffing fails, falls back to current visible screen
- Output prefixed with `"New Terminal Output:\n"` or `"Current Terminal Screen:\n"`
- **Output truncation:** Limited to 10KB (`_limit_output_length = 10_000`), preserving first and last halves

### Sending Keystrokes

```bash
tmux send-keys -t {session_name} {keys}
```

- Keys are shell-quoted via `shlex.quote()`
- **16KB command length limit** (`_TMUX_SEND_KEYS_MAX_COMMAND_LENGTH = 16_000`)
- Oversized commands split across multiple `send-keys` invocations using `_split_key_for_tmux` (binary search for optimal chunk size)

### Command Completion Detection

Two modes:

**Blocking mode:** Appends `"; tmux wait -S done"` and `"Enter"` to keystrokes, then runs `timeout {max_timeout_sec}s tmux wait done`. Default `max_timeout_sec=180`.

**Non-blocking mode (default in practice):** Just sleeps for `min_timeout_sec` (the `duration` from the LLM's response). Duration capped at 60 seconds in `_handle_llm_interaction`.

### Special Keys

Enter keys recognized: `{"Enter", "C-m", "KPEnter", "C-j", "^M", "^J"}`.

`_prevent_execution` strips trailing enter keys when needed. Special keys (`C-c`, `C-d`) sent as individual keystrokes via tmux's native key name support.

---

## LLM / Planner Integration

### Prompt Construction

Template loaded from `templates/terminus-json-plain.txt` or `templates/terminus-xml-plain.txt` based on `parser_name` (default: `"json"`).

Template placeholders: `{instruction}` (task description) and `{terminal_state}` (current terminal output).

The prompt instructs the LLM to:
- Analyze current terminal state
- Plan next steps
- Return commands as keystrokes with duration estimates

### Response Format (JSON template)

LLM returns structured response with:
- `analysis` — current state analysis
- `plan` — next steps
- `commands` — array of `{"keystrokes": "...", "duration": 0.1}` objects
- `task_complete` — boolean

### Response Format (XML template)

```xml
<response>
  <analysis>...</analysis>
  <plan>...</plan>
  <commands>
    <keystrokes duration="0.1">ls -la</keystrokes>
    <keystrokes duration="1.0">make build</keystrokes>
  </commands>
  <task_complete>false</task_complete>
</response>
```

Duration guidance from prompt:
- 0.1s for simple commands (ls, cat)
- 1.0s for compilation
- Longer for slow tasks
- Never >60s

### Model Parameters

| Parameter | Default |
|-----------|---------|
| `temperature` | 0.7 |
| `max_turns` | 1,000,000 |
| `reasoning_effort` | configurable (none/minimal/low/medium/high/default) |
| `max_thinking_tokens` | minimum 1024 |
| `interleaved_thinking` | optional |

Backend: LiteLLM (default) or Tinker.

### Output Parsing

Two parsers: `TerminusJSONPlainParser` and `TerminusXMLPlainParser`.

Both return `ParseResult`:
```python
ParseResult(
    commands: list[ParsedCommand],
    is_task_complete: bool,
    error: str | None,
    warning: str | None,
    analysis: str | None,
    plan: str | None
)
```

Where `ParsedCommand` is:
```python
ParsedCommand(keystrokes: str, duration: float)
```

**Auto-fix capabilities:**
- JSON parser: tries adding missing closing braces, extracting JSON from mixed content
- XML parser: fixes missing `</response>` tags, salvages truncated responses
- Field order validation warns if analysis/plan/commands appear out of order

---

## Summarization / Handoff

### Trigger Conditions

- **Proactive:** Free tokens < `proactive_summarization_threshold` (default: 8000 tokens)
- **Reactive:** On `ContextLengthExceededError`

### Three-Subagent Pipeline

**Subagent 1 — Summary Generation:**
- Input: unwound chat messages (after token freeing via `_unwind_messages_to_free_tokens`, which removes message pairs from the end until 4000 tokens are free)
- Prompt: asks for comprehensive summary covering major actions, important info, challenging problems, current status
- Output: summary text

**Subagent 2 — Question Asking:**
- Input: original task + summary from step 1 + current terminal screen
- Message history: **empty** (fresh start, no prior chat)
- Prompt: generate at least 5 questions about info missing from the summary
- Output: list of questions

**Subagent 3 — Answer Providing:**
- Input: the questions from step 2
- Message history: full unwound chat + summary prompt + summary response
- Prompt: answer each question in detail
- Output: detailed answers

### Context Replacement

After handoff, chat history is replaced with:
```
[system_message, question_prompt (includes summary), model_questions]
```
Answers delivered as next user prompt:
```
"Here are the answers the other agent provided.\n\n{answers}\n\nContinue working on this task..."
```

### Fallback Chain on ContextLengthExceededError

1. Full 3-subagent summarization
2. Short summary — single LLM call with last 1000 chars of screen
3. Ultimate fallback — just the original instruction + last 1000 chars, no LLM call

---

## Trajectory / ATIF Format

Each step is a `Step` dataclass:

| Field | Description |
|-------|-------------|
| `step_id` | Unique identifier |
| `timestamp` | UTC ISO format |
| `source` | `"user"` / `"agent"` / `"system"` |
| `model_name` | Model used |
| `message` | Text content |
| `reasoning_content` | Chain-of-thought if available |
| `tool_calls` | List of `ToolCall` |
| `observation` | `ObservationResult` (terminal output or subagent ref) |
| `metrics` | Per-step token counts, cost, logprobs |
| `is_copied_context` | Whether from summarization handoff |
| `extra` | Additional metadata |

Commands represented as tool calls:
- `function_name="bash_command"`, `arguments={"keystrokes": ..., "duration": ...}`
- Task completion: `function_name="mark_task_complete"`

Trajectories dumped after every episode. Output limited to 10KB with first/last halves preserved.

---

## Action Model

Terminus has **no action abstraction layer**. It sends raw keystrokes through tmux's `send-keys`.

- Multi-line input: literal newlines in the keystrokes string
- Special keys: `C-c`, `C-d` sent as individual keystrokes via tmux native key names
- All interaction is keystrokes + duration (wait time after sending)
- Single tmux session, single pane — no multi-pane/window management

---

## Configuration Summary

| Parameter | Default | Description |
|-----------|---------|-------------|
| `temperature` | 0.7 | LLM sampling temperature |
| `max_turns` | 1,000,000 | Max agent loop iterations |
| `parser_name` | `"json"` | `"json"` or `"xml"` |
| `enable_summarize` | `True` | Enable context summarization |
| `proactive_summarization_threshold` | 8000 | Free tokens before triggering |
| `tmux_pane_width` | 160 | Terminal columns |
| `tmux_pane_height` | 40 | Terminal rows |
| `history_limit` | 10,000,000 | tmux scrollback lines |
| `max_timeout_sec` | 180 | Blocking command timeout |
| `_limit_output_length` | 10,000 bytes | Terminal output truncation |
| `_TMUX_SEND_KEYS_MAX_COMMAND_LENGTH` | 16,000 chars | tmux command length limit |
| `retry_attempts` | 3 | LLM call retries |

---

## Key Design Decisions

1. **Keystroke-only interaction** — no file-edit tools, no bash-execute abstractions. Maximum flexibility, no model bias.
2. **Outside the environment** — agent process runs separately from execution container.
3. **Model-agnostic** — LiteLLM backend supports any provider.
4. **Single pane** — no multi-pane/window management complexity.
5. **Duration-based waiting** — LLM estimates how long to wait after each command, capped at 60s.
6. **Resilient parsing** — auto-fix for malformed LLM output, error feedback loop instead of crash.
7. **Three-stage summarization** — summary → questions → answers preserves critical context across handoffs.
