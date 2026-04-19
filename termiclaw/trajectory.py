"""ATIF-style JSONL trajectory logging."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from termiclaw.models import RunInfo

if TYPE_CHECKING:
    from termiclaw.models import StepRecord
    from termiclaw.state import State


def read_trajectory_text(run_dir: Path, *, max_chars: int = 50_000) -> str:
    """Read trajectory.jsonl and return a human-readable summary.

    Reads from the end of the file to stay within max_chars.
    Used for summarization full_steps_text.
    """
    trajectory_path = run_dir / "trajectory.jsonl"
    if not trajectory_path.exists():
        return ""
    lines = trajectory_path.read_text(encoding="utf-8").strip().splitlines()
    parts: list[str] = []
    total = 0
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        step_id = str(entry.get("step_id", "?"))[:8]
        message = str(entry.get("message", ""))
        observation = entry.get("observation")
        obs = ""
        if isinstance(observation, dict):
            obs = str(observation.get("terminal_output", ""))[:200]
        error = entry.get("error")
        part = f"[{step_id}] {message}"
        if obs:
            part += f"\n  Output: {obs}"
        if error:
            part += f"\n  Error: {error}"
        if total + len(part) > max_chars:
            break
        parts.append(part)
        total += len(part)
    parts.reverse()
    return "\n\n".join(parts)


def ensure_run_dir(runs_dir: str, run_id: str) -> Path:
    """Create and return the run directory."""
    run_dir = Path(runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def append_step(run_dir: Path, step: StepRecord) -> None:
    """Append a step record as JSONL to trajectory.jsonl."""
    entry = _step_to_dict(step)
    trajectory_path = run_dir / "trajectory.jsonl"
    with trajectory_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str))
        f.write("\n")


def write_run_metadata(
    run_dir: Path,
    state: State,
    *,
    finished_at: str | None = None,
    termination_reason: str | None = None,
) -> None:
    """Write run.json with run metadata."""
    metadata = {
        "run_id": state.run_id,
        "instruction": state.instruction,
        "started_at": state.started_at,
        "finished_at": finished_at,
        "status": state.status,
        "total_steps": state.current_step,
        "tmux_session": state.tmux_session,
        "termination_reason": termination_reason,
    }
    run_json_path = run_dir / "run.json"
    with run_json_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str)
        f.write("\n")


def _step_to_dict(step: StepRecord) -> dict[str, object]:
    """Convert a StepRecord to an ATIF-compatible dict."""
    tool_calls: list[dict[str, object]] = []

    if step.task_complete:
        tool_calls.append(
            {"function_name": "mark_task_complete", "arguments": {}},
        )
    else:
        for cmd in step.commands:
            tool_calls.append(
                {
                    "function_name": "bash_command",
                    "arguments": {
                        "keystrokes": cmd.keystrokes,
                        "duration": cmd.duration,
                    },
                },
            )

    return {
        "step_id": step.step_id,
        "timestamp": step.timestamp,
        "source": step.source,
        "message": step.analysis or "",
        "tool_calls": tool_calls,
        "observation": {
            "terminal_output": step.observation,
        },
        "metrics": dict(step.metrics),
        "is_copied_context": step.is_copied_context,
        "error": step.error,
    }


def list_runs(runs_dir: str) -> list[RunInfo]:
    """List all runs with metadata. Sorted by start time, newest first."""
    runs_path = Path(runs_dir)
    if not runs_path.exists():
        return []
    results: list[RunInfo] = []
    for entry in runs_path.iterdir():
        if not entry.is_dir():
            continue
        run_json = entry / "run.json"
        if not run_json.exists():
            continue
        try:
            meta = json.loads(run_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        started = str(meta.get("started_at", ""))
        finished = str(meta.get("finished_at", ""))
        info = RunInfo(
            run_id=str(meta.get("run_id", "")),
            instruction=str(meta.get("instruction", "")),
            status=str(meta.get("status", "")),
            total_steps=int(meta.get("total_steps", 0)),
            started_at=started,
            finished_at=finished,
            tmux_session=str(meta.get("tmux_session", "")),
            termination_reason=str(meta.get("termination_reason", "")),
            prompt_tokens=_sum_prompt_tokens(entry),
            duration=_format_duration(started, finished),
        )
        results.append(info)
    results.sort(key=lambda r: r.started_at, reverse=True)
    return results


def _sum_prompt_tokens(run_dir: Path) -> int:
    """Sum prompt_tokens from all trajectory steps."""
    trajectory_path = run_dir / "trajectory.jsonl"
    if not trajectory_path.exists():
        return 0
    total = 0
    for line in trajectory_path.read_text(encoding="utf-8").strip().splitlines():
        try:
            entry = json.loads(line)
            metrics = entry.get("metrics", {})
            if isinstance(metrics, dict):
                total += int(metrics.get("prompt_tokens", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return total


_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


def _format_duration(started_at: str, finished_at: str) -> str:
    """Format duration between two ISO timestamps as human-readable string."""
    if not started_at or not finished_at:
        return "-"
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(finished_at)
    except ValueError:
        return "-"
    delta = end - start
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "-"
    if total_seconds < _SECONDS_PER_MINUTE:
        return f"{total_seconds}s"
    minutes = total_seconds // _SECONDS_PER_MINUTE
    seconds = total_seconds % _SECONDS_PER_MINUTE
    if minutes < _MINUTES_PER_HOUR:
        return f"{minutes}m {seconds}s"
    hours = minutes // _MINUTES_PER_HOUR
    minutes = minutes % _MINUTES_PER_HOUR
    return f"{hours}h {minutes}m"
