"""ATIF v1.6 trajectory export.

Converts a completed termiclaw run (run.json + trajectory.jsonl) into the
Agent Trajectory Interchange Format used by Terminal-Bench and related
harnesses. The schema is embedded as a literal dict so we don't depend on
the upstream ATIF repo; `schema_version` is always `"1.6"`.

Reference: laude-institute/harbor RFC 0001 (ATIF v1.6).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from termiclaw.errors import ParseError
from termiclaw.result import Err, Ok
from termiclaw.validate import require_dict

if TYPE_CHECKING:
    from pathlib import Path

    from termiclaw.result import Result

_SCHEMA_VERSION = "1.6"


@dataclass(frozen=True, slots=True)
class AtifToolCall:
    """One tool call emitted by the planner in a single step."""

    function_name: str
    arguments: dict[str, str | float | int | bool]


@dataclass(frozen=True, slots=True)
class AtifObservation:
    """Environment response the planner observed after its tool calls."""

    terminal_output: str


@dataclass(frozen=True, slots=True)
class AtifMetrics:
    """Per-step metrics carried through the trajectory."""

    prompt_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    planner_duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class AtifStep:
    """One step in an ATIF v1.6 trajectory."""

    step_id: str
    timestamp: str
    source: str
    message: str
    tool_calls: list[AtifToolCall]
    observation: AtifObservation
    metrics: AtifMetrics
    is_copied_context: bool
    error: str | None
    # v1.6 additions; we leave these blank since we don't capture them yet.
    model_name: str = ""
    reasoning_content: str | None = None


@dataclass(frozen=True, slots=True)
class AtifRun:
    """A complete ATIF v1.6 run export."""

    schema_version: str
    run_id: str
    session_id: str
    instruction: str
    started_at: str
    finished_at: str
    status: str
    steps: list[AtifStep] = field(default_factory=list)


def export_run(run_id: str, runs_dir: Path) -> Result[AtifRun, ParseError]:
    """Read a run directory and build an AtifRun.

    Returns Err(ParseError) on missing/malformed metadata. The trajectory
    may be empty (zero steps); that's not an error.
    """
    run_dir = runs_dir / run_id
    if not run_dir.is_dir():
        return Err(ParseError("run_dir", f"not a directory: {run_dir}", str(run_dir)))
    meta_result = _load_run_meta(run_dir)
    if isinstance(meta_result, Err):
        return meta_result
    meta = meta_result.value
    steps = _load_trajectory(run_dir)
    return Ok(
        AtifRun(
            schema_version=_SCHEMA_VERSION,
            run_id=str(meta.get("run_id", run_id)),
            session_id=str(meta.get("claude_session_id", "")),
            instruction=str(meta.get("instruction", "")),
            started_at=str(meta.get("started_at", "")),
            finished_at=str(meta.get("finished_at") or ""),
            status=str(meta.get("status", "")),
            steps=steps,
        ),
    )


def atif_to_json(run: AtifRun) -> str:
    """Serialize an AtifRun to JSON (ATIF v1.6 shape)."""
    return json.dumps(asdict(run), indent=2, default=str)


def _load_run_meta(run_dir: Path) -> Result[dict[str, object], ParseError]:
    """Load and narrow run.json to a string-keyed dict."""
    run_json = run_dir / "run.json"
    if not run_json.exists():
        return Err(ParseError("run.json", "missing", str(run_json)))
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return Err(ParseError("run.json", f"invalid JSON: {e}", str(run_json)))
    return require_dict(data, "run.json", raw=str(run_json))


def _load_trajectory(run_dir: Path) -> list[AtifStep]:
    """Read trajectory.jsonl; skip malformed lines rather than failing the export."""
    traj = run_dir / "trajectory.jsonl"
    if not traj.exists():
        return []
    steps: list[AtifStep] = []
    for raw_line in traj.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = require_dict(entry, "step", raw=line[:200])
        if isinstance(result, Err):
            continue
        steps.append(_entry_to_step(result.value))
    return steps


def _entry_to_step(entry: dict[str, object]) -> AtifStep:  # boundary: parsing raw JSONL
    """Map one trajectory.jsonl entry to an AtifStep."""
    tool_calls = _parse_tool_calls(entry.get("tool_calls"))
    terminal = _parse_observation(entry.get("observation"))
    metrics = _parse_metrics(entry.get("metrics"))

    error = entry.get("error")
    return AtifStep(
        step_id=str(entry.get("step_id", "")),
        timestamp=str(entry.get("timestamp", "")),
        source=str(entry.get("source", "")),
        message=str(entry.get("message", "") or ""),
        tool_calls=tool_calls,
        observation=AtifObservation(terminal_output=terminal),
        metrics=metrics,
        is_copied_context=bool(entry.get("is_copied_context", False)),
        error=str(error) if error else None,
    )


def _parse_tool_calls(raw: object) -> list[AtifToolCall]:
    """Extract tool_calls list from a raw JSON value."""
    if not isinstance(raw, list):
        return []
    calls: list[AtifToolCall] = []
    for item in raw:
        narrowed = require_dict(item, "tool_call")
        if isinstance(narrowed, Err):
            continue
        d = narrowed.value
        fn_raw = d.get("function_name", "")
        fn = fn_raw if isinstance(fn_raw, str) else ""
        args_raw = d.get("arguments")
        typed_args: dict[str, str | float | int | bool] = {}
        if isinstance(args_raw, dict):
            for k, v in args_raw.items():
                if isinstance(v, (str, int, float, bool)):
                    typed_args[str(k)] = v
        calls.append(AtifToolCall(function_name=fn, arguments=typed_args))
    return calls


def _parse_observation(raw: object) -> str:
    """Extract observation.terminal_output from a raw JSON value."""
    narrowed = require_dict(raw, "observation")
    if isinstance(narrowed, Err):
        return ""
    terminal = narrowed.value.get("terminal_output")
    return terminal if isinstance(terminal, str) else ""


def _parse_metrics(raw: object) -> AtifMetrics:
    """Extract metrics from a raw JSON value."""
    narrowed = require_dict(raw, "metrics")
    if isinstance(narrowed, Err):
        return AtifMetrics()
    d = narrowed.value
    return AtifMetrics(
        prompt_tokens=_int(d.get("prompt_tokens")),
        input_tokens=_int(d.get("input_tokens")),
        output_tokens=_int(d.get("output_tokens")),
        cost_usd=_float(d.get("cost_usd")),
        planner_duration_ms=_int(d.get("planner_duration_ms")),
    )


def _int(value: object) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0
