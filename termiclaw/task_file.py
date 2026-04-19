"""Task file loader: parse TOML task specs into `TaskSpec` dataclasses.

Task files describe a task with its success condition. They power
`termiclaw eval` and `termiclaw mcts`.

Format:

    instruction = "Create /tmp/hello.txt with 'hello world'."

    [verifier]
    command = "cat /tmp/hello.txt"
    expected_exit = 0
    expected_output_pattern = "^hello world\\s*$"
    timeout_seconds = 5
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from termiclaw.errors import ParseError
from termiclaw.result import Err, Ok
from termiclaw.validate import (
    optional_float,
    optional_str,
    require_dict,
    required_int,
    required_str,
)
from termiclaw.verifier import VerifierSpec

if TYPE_CHECKING:
    from pathlib import Path

    from termiclaw.result import Result


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """A single task loaded from disk."""

    name: str  # derived from filename (without .toml)
    instruction: str
    verifier: VerifierSpec | None = None


def load_task(path: Path) -> Result[TaskSpec, ParseError]:
    """Parse a single task TOML file. Returns `Ok(TaskSpec)` or `Err(ParseError)`."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return Err(ParseError("<file>", f"unreadable: {e}", str(path)))
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        return Err(ParseError("<toml>", f"invalid TOML: {e}", str(path)))

    obj_r = require_dict(data, "<root>", raw=str(path))
    if isinstance(obj_r, Err):
        return obj_r
    obj = obj_r.value

    instruction_r = required_str(obj, "instruction")
    if isinstance(instruction_r, Err):
        return instruction_r

    verifier: VerifierSpec | None = None
    raw_verifier = obj.get("verifier")
    if raw_verifier is not None:
        verifier_r = _parse_verifier(raw_verifier)
        if isinstance(verifier_r, Err):
            return verifier_r
        verifier = verifier_r.value

    return Ok(
        TaskSpec(
            name=path.stem,
            instruction=instruction_r.value,
            verifier=verifier,
        ),
    )


def _parse_verifier(raw: object) -> Result[VerifierSpec, ParseError]:
    """Parse the `[verifier]` table into a `VerifierSpec`."""
    obj_r = require_dict(raw, "verifier")
    if isinstance(obj_r, Err):
        return obj_r
    obj = obj_r.value

    command_r = required_str(obj, "command")
    if isinstance(command_r, Err):
        return command_r
    exit_r = _optional_int(obj, "expected_exit", default=0)
    if isinstance(exit_r, Err):
        return exit_r
    pattern_r = optional_str(obj, "expected_output_pattern", default="")
    if isinstance(pattern_r, Err):
        return pattern_r
    timeout_r = optional_float(obj, "timeout_seconds", default=30.0)
    if isinstance(timeout_r, Err):
        return timeout_r

    pattern = pattern_r.value or None
    return Ok(
        VerifierSpec(
            command=command_r.value,
            expected_exit=exit_r.value,
            expected_output_pattern=pattern,
            timeout_seconds=timeout_r.value,
        ),
    )


def _optional_int(
    d: dict[str, object],
    field: str,
    default: int,
) -> Result[int, ParseError]:
    """Local helper: optional int (validate.required_int has no optional variant)."""
    if field not in d:
        return Ok(default)
    return required_int(d, field)


def load_tasks_dir(path: Path) -> Result[list[TaskSpec], ParseError]:
    """Load every `*.toml` file in a directory into TaskSpec instances."""
    if not path.is_dir():
        return Err(ParseError("<dir>", "not a directory", str(path)))
    tasks: list[TaskSpec] = []
    for p in sorted(path.glob("*.toml")):
        result = load_task(p)
        if isinstance(result, Err):
            return result
        tasks.append(result.value)
    return Ok(tasks)
