"""Claude Code planner: invocation, response parsing, auto-fix."""

from __future__ import annotations

import json
import subprocess

from termiclaw.logging import get_logger
from termiclaw.models import ParsedCommand, ParseResult

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


def parse_response(raw_stdout: str) -> ParseResult:
    """Parse claude -p JSON envelope and extract structured action."""
    try:
        envelope = json.loads(raw_stdout)
    except (json.JSONDecodeError, TypeError):
        return ParseResult(error=f"Failed to parse CLI envelope: {raw_stdout[:500]}")

    if not isinstance(envelope, dict):
        return ParseResult(error=f"Envelope is not a dict: {raw_stdout[:500]}")

    text = envelope.get("result", "")
    if not isinstance(text, str) or not text.strip():
        return ParseResult(error=f"Empty or missing result field: {raw_stdout[:500]}")

    obj = _try_parse_json(text)
    if obj is None:
        return ParseResult(error=f"Failed to parse planner JSON: {text[:500]}")

    return _map_to_parse_result(obj)


def _map_to_parse_result(obj: dict[str, object]) -> ParseResult:
    """Map a parsed JSON dict to a ParseResult."""
    commands = _extract_commands(obj.get("commands"))
    warning = _check_field_order(obj)

    return ParseResult(
        analysis=str(obj.get("analysis", "")),
        plan=str(obj.get("plan", "")),
        commands=commands,
        task_complete=bool(obj.get("task_complete", False)),
        warning=warning,
    )


def _extract_commands(raw: object) -> tuple[ParsedCommand, ...]:
    """Extract commands from the raw JSON commands field."""
    if not isinstance(raw, list):
        return ()
    result: list[ParsedCommand] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_dict: dict[str, object] = {str(k): v for k, v in item.items()}
        keystrokes = str(item_dict.get("keystrokes", ""))
        if not keystrokes:
            continue
        duration = _parse_duration(item_dict.get("duration"))
        result.append(ParsedCommand(keystrokes=keystrokes, duration=duration))
    return tuple(result)


def _parse_duration(raw: object) -> float:
    """Parse and cap a duration value."""
    if raw is None:
        return _DEFAULT_DURATION
    try:
        return min(float(str(raw)), _MAX_DURATION)
    except (ValueError, TypeError):
        return _DEFAULT_DURATION


def _check_field_order(obj: dict[str, object]) -> str | None:
    """Warn if JSON fields are out of expected order."""
    fields = list(obj.keys())
    expected_order = ["analysis", "plan", "commands", "task_complete"]
    field_positions = [fields.index(f) for f in expected_order if f in fields]
    if field_positions != sorted(field_positions):
        return f"Fields out of expected order: {fields}"
    return None


def _try_parse_json(text: str) -> dict[str, object] | None:
    """Multi-stage JSON parser with auto-fix."""
    # Stage 1: direct parse
    result = _try_loads(text)
    if result is not None:
        return result

    # Stage 2: strip markdown code fences
    stripped = _strip_code_fences(text)
    if stripped != text:
        result = _try_loads(stripped)
        if result is not None:
            return result

    # Stage 3: add missing closing braces
    result = _try_add_closing_braces(stripped)
    if result is not None:
        return result

    # Stage 4: extract JSON from mixed text
    return _try_extract_json(text)


def _try_loads(text: str) -> dict[str, object] | None:
    """Try json.loads, return dict or None."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(obj, dict):
        return obj
    return None


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences."""
    lines = text.strip().splitlines()
    min_fenced_lines = 2
    if len(lines) >= min_fenced_lines and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text.strip()


def _try_add_closing_braces(text: str) -> dict[str, object] | None:
    """Try appending closing braces/brackets to fix truncated JSON."""
    candidate = text.rstrip()
    for suffix in ["}", "}}", "}}}", "]}", "]}}", "]}}}", "}]}"]:
        result = _try_loads(candidate + suffix)
        if result is not None:
            return result
    return None


def _try_extract_json(text: str) -> dict[str, object] | None:
    """Find first { to last } and try to parse."""
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace == -1 or last_brace == -1 or first_brace >= last_brace:
        return None
    candidate = text[first_brace : last_brace + 1]
    return _try_loads(candidate)


def query_planner(prompt: str, *, timeout: int = 300, retries: int = 3) -> str:
    """Invoke claude -p and return raw stdout."""
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--output-format",
                    "json",
                    "--max-turns",
                    "1",
                    "--allowedTools",
                    "",
                ],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode != 0:
                _log.warning(
                    "claude -p failed",
                    extra={"attempt": attempt + 1, "exit_code": result.returncode},
                )
                last_error = subprocess.CalledProcessError(result.returncode, "claude")
            else:
                return result.stdout
        except subprocess.TimeoutExpired as exc:
            _log.warning(
                "claude -p timed out",
                extra={"attempt": attempt + 1, "timeout": timeout},
            )
            last_error = exc

    msg = f"Planner failed after {retries} attempts"
    raise RuntimeError(msg) from last_error
