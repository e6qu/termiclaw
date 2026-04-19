"""Claude Code planner: invocation, response parsing, auto-fix."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from termiclaw.errors import (
    ParseError,
    PlannerSubprocessError,
    PlannerTimeoutError,
)
from termiclaw.logging import get_logger
from termiclaw.models import ParsedCommand, ParseResult, PlannerUsage
from termiclaw.result import Err, Ok
from termiclaw.validate import (
    optional_float,
    optional_list,
    require_dict,
    require_json_object,
    required_bool,
    required_str,
)

if TYPE_CHECKING:
    from termiclaw.errors import PlannerError
    from termiclaw.result import Result

_log = get_logger("planner")

_PROMPT_TEMPLATE = """\
You are a terminal agent. You interact with a Linux/macOS terminal \
through a tmux session. You can only send keystrokes — you have no \
other tools.

Your task:
{instruction}

{summary_section}\
Current terminal state:
{terminal_state}

Respond with a JSON object containing:

1. "analysis": Brief analysis of the current terminal state and \
what has happened since your last action.

2. "plan": Your plan for the next step(s) to accomplish the task.

3. "commands": An array of commands to execute. Each command is an \
object with:
   - "keystrokes": The exact text/keys to send to the terminal. \
Each command object should be ONE shell command or action. \
Include \\n at the end to press Enter. \
For special keys (C-c, C-d, Up, Down, Escape), use a separate \
command object with just the key name and no \\n.
   - "duration": How long to wait (in seconds) after sending \
this command before capturing output. \
Guidelines: 0.1 for simple commands (ls, cat, echo), \
0.5 for moderate commands (grep, find), \
1.0-5.0 for compilation or installation, \
10.0-30.0 for long-running tasks. \
Never exceed 60 seconds.

4. "task_complete": Set to true ONLY when you are confident the \
task is fully completed. You will be asked to confirm.

Respond ONLY with the JSON object. No markdown, no explanation \
outside the JSON.

Example response:
{{"analysis": "The shell is at a bash prompt.", \
"plan": "Check the project structure.", \
"commands": [{{"keystrokes": "ls -la\\n", "duration": 0.5}}], \
"task_complete": false}}
"""

_MAX_DURATION = 60.0
_DEFAULT_DURATION = 0.5

_AUTONOMY_DOCTRINE = """\
Autonomy rules:
- You will never ask the user for input or clarification. If the task \
is ambiguous, make a reasonable choice and keep working.
- If a command produces the same output as last time, you are stuck. \
Try a different approach: change the command, inspect the process, \
or send C-c and retry.
- If you appear to be inside an interactive program you did not intend \
to enter (vim, less, a REPL, a pager, a confirmation prompt), exit \
it first with C-c, q, :q!, Escape, or the appropriate key. Do not \
leave the terminal inside an interactive program between turns.
- If a long-running command has produced no new output for multiple \
turns, interrupt it with C-c and either retry with a blocking wait \
or investigate why it hung.
- task_complete=true is for when the task is done, not when you are \
stuck. If stuck, keep trying.
- Never set task_complete=true on your very first response: you have \
not yet sent any keystrokes, so no task can have been performed. Your \
first response must contain at least one command in "commands". \
task_complete=true is only appropriate after the terminal shows \
evidence that the work actually happened.
"""

PROMPT_VERSION = "2"

_PLANNER_SCHEMA = json.dumps(
    {
        "type": "object",
        "required": ["analysis", "plan", "commands", "task_complete"],
        "properties": {
            "analysis": {"type": "string"},
            "plan": {"type": "string"},
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["keystrokes"],
                    "properties": {
                        "keystrokes": {"type": "string"},
                        "duration": {"type": "number"},
                    },
                },
            },
            "task_complete": {"type": "boolean"},
        },
    },
)


def estimate_tokens(text: str) -> int:
    """Pre-flight token estimate for trigger decisions.

    `len // 4` is the stdlib-only approximation. Ground truth comes from
    the claude -p usage envelope after each call.
    """
    return max(1, len(text) // 4)


def build_prompt(
    instruction: str,
    terminal_state: str,
    summary: str | None = None,
    qa_context: str | None = None,
) -> str:
    """Assemble the full planner prompt."""
    summary_section = ""
    if summary is not None:
        summary_section = f"Summary of progress so far:\n{summary}\n\n"
        if qa_context:
            summary_section += (
                f"Additional context (Q&A from prior summarization):\n{qa_context}\n\n"
            )
    return _PROMPT_TEMPLATE.format(
        instruction=instruction,
        summary_section=summary_section,
        terminal_state=terminal_state,
    )


def parse_response(raw_stdout: str) -> Result[ParseResult, ParseError]:  # noqa: PLR0911
    """Parse claude -p JSON envelope and extract structured action.

    With `--json-schema`, Claude Code puts the schema-valid response in
    the `structured_output` field (as a dict), not in `result` (which
    stays empty on schema runs). Fall back to parsing `result` as JSON
    text for backward compatibility.
    """
    envelope_result = require_json_object(raw_stdout)
    if isinstance(envelope_result, Err):
        return envelope_result
    envelope = envelope_result.value

    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        body_result = require_dict(structured, "structured_output", raw=raw_stdout[:500])
        if isinstance(body_result, Err):
            return body_result
        return _map_to_parse_result(body_result.value)

    text_result = required_str(envelope, "result")
    if isinstance(text_result, Err):
        return text_result
    text = text_result.value
    if not text.strip():
        return Err(ParseError("result", "empty string", raw_stdout[:500]))

    body_result = require_json_object(text)
    if isinstance(body_result, Err):
        return body_result
    return _map_to_parse_result(body_result.value)


def _map_to_parse_result(obj: dict[str, object]) -> Result[ParseResult, ParseError]:
    """Map a validated JSON dict to a ParseResult."""
    analysis_r = required_str(obj, "analysis")
    if isinstance(analysis_r, Err):
        return analysis_r
    plan_r = required_str(obj, "plan")
    if isinstance(plan_r, Err):
        return plan_r
    commands_r = _extract_commands(obj)
    if isinstance(commands_r, Err):
        return commands_r
    task_complete_r = required_bool(obj, "task_complete")
    if isinstance(task_complete_r, Err):
        return task_complete_r

    warning = _check_field_order(obj)
    return Ok(
        ParseResult(
            analysis=analysis_r.value,
            plan=plan_r.value,
            commands=commands_r.value,
            task_complete=task_complete_r.value,
            warning=warning,
        ),
    )


def _extract_commands(
    obj: dict[str, object],
) -> Result[tuple[ParsedCommand, ...], ParseError]:
    """Extract and validate the `commands` array."""
    raw_result = optional_list(obj, "commands")
    if isinstance(raw_result, Err):
        return raw_result
    parsed: list[ParsedCommand] = []
    for i, item in enumerate(raw_result.value):
        item_dict_r = require_dict(item, f"commands[{i}]")
        if isinstance(item_dict_r, Err):
            return item_dict_r
        cmd_r = _parse_command(item_dict_r.value, i)
        if isinstance(cmd_r, Err):
            return cmd_r
        parsed.append(cmd_r.value)
    return Ok(tuple(parsed))


def _parse_command(d: dict[str, object], idx: int) -> Result[ParsedCommand, ParseError]:
    """Validate a single command dict into a ParsedCommand."""
    keystrokes_r = required_str(d, "keystrokes")
    if isinstance(keystrokes_r, Err):
        return Err(ParseError(f"commands[{idx}].keystrokes", keystrokes_r.error.reason, repr(d)))
    keystrokes = keystrokes_r.value
    if not keystrokes:
        return Err(ParseError(f"commands[{idx}].keystrokes", "empty string", repr(d)))
    duration_r = optional_float(d, "duration", _DEFAULT_DURATION)
    if isinstance(duration_r, Err):
        return Err(ParseError(f"commands[{idx}].duration", duration_r.error.reason, repr(d)))
    return Ok(
        ParsedCommand(
            keystrokes=keystrokes,
            duration=min(duration_r.value, _MAX_DURATION),
        ),
    )


def _check_field_order(obj: dict[str, object]) -> str | None:
    """Warn if JSON fields are out of expected order."""
    fields = list(obj.keys())
    expected_order = ["analysis", "plan", "commands", "task_complete"]
    field_positions = [fields.index(f) for f in expected_order if f in fields]
    if field_positions != sorted(field_positions):
        return f"Fields out of expected order: {fields}"
    return None


def extract_usage(raw_stdout: str) -> PlannerUsage:
    """Extract token/cost metrics + session_id from the claude -p JSON envelope."""
    try:
        envelope = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        return PlannerUsage()
    if not isinstance(envelope, dict):
        return PlannerUsage()
    usage = envelope.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = int(usage.get("input_tokens", 0))
    cache_read_input_tokens = int(usage.get("cache_read_input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    cost_usd = float(envelope.get("total_cost_usd", 0.0))
    duration_ms = int(envelope.get("duration_ms", 0))
    session_id = str(envelope.get("session_id", ""))
    return PlannerUsage(
        input_tokens=input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        claude_session_id=session_id,
    )


def _build_session_args(
    *,
    claude_session_id: str,
    first_call: bool,
    resume_parent: str | None,
    fork_session: bool,
) -> list[str]:
    """Construct the claude -p session-related argv."""
    if resume_parent:
        args = ["--resume", resume_parent]
        if fork_session:
            args.append("--fork-session")
        return args
    if claude_session_id and first_call:
        return ["--session-id", claude_session_id]
    if claude_session_id:
        return ["--resume", claude_session_id]
    return []


def query_planner(  # noqa: PLR0913 — all kwargs are discrete session knobs
    prompt: str,
    *,
    timeout: int = 300,
    retries: int = 3,
    claude_session_id: str = "",
    first_call: bool = False,
    resume_parent: str | None = None,
    fork_session: bool = False,
) -> Result[str, PlannerError]:
    """Invoke claude -p and return raw stdout as `Ok(stdout)` or `Err(PlannerError)`.

    Session semantics (per feature #10):
    - `claude_session_id` set + `first_call=True`: creates session with that ID.
    - `claude_session_id` set + `first_call=False`: resumes that session.
    - `resume_parent` set: resumes parent's session; `fork_session=True` branches.
    """
    last_error: PlannerError = PlannerSubprocessError(0, "no attempts made")
    for attempt in range(retries):
        # After the first attempt with `--session-id`, subsequent retries
        # must use `--resume`: claude CLI reserves the id on attempt 1,
        # and any retry still passing `--session-id X` is rejected with
        # "Session ID is already in use." (see BUG-35).
        session_args = _build_session_args(
            claude_session_id=claude_session_id,
            first_call=first_call and attempt == 0,
            resume_parent=resume_parent,
            fork_session=fork_session and attempt == 0,
        )
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--output-format",
                    "json",
                    # Claude Code with `--json-schema` schema enforcement
                    # needs ≥2 turns internally (one to think, one to
                    # emit the schema-valid JSON). `--max-turns 1` trips
                    # `subtype=error_max_turns` and exits non-zero even
                    # on success — see BUG-36.
                    "--max-turns",
                    "4",
                    "--allowedTools",
                    "",
                    "--json-schema",
                    _PLANNER_SCHEMA,
                    "--append-system-prompt",
                    _AUTONOMY_DOCTRINE,
                    *session_args,
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            _log.warning(
                "claude -p timed out",
                extra={"attempt": attempt + 1, "timeout": timeout},
            )
            last_error = PlannerTimeoutError(float(timeout))
            continue
        if result.returncode != 0:
            _log.warning(
                "claude -p failed",
                extra={"attempt": attempt + 1, "exit_code": result.returncode},
            )
            last_error = PlannerSubprocessError(result.returncode, result.stderr or "")
            continue
        return Ok(result.stdout)

    widened: Err[PlannerError] = Err(last_error)
    return widened
