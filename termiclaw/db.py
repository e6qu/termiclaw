"""SQLite session database for extended tracking and fast queries."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING

from termiclaw.logging import log_dir
from termiclaw.models import RunInfo

if TYPE_CHECKING:
    from pathlib import Path

    from termiclaw.models import RunState, StepRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    instruction TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    tmux_session TEXT NOT NULL,
    termination_reason TEXT,
    total_steps INTEGER NOT NULL DEFAULT 0,
    total_prompt_chars INTEGER NOT NULL DEFAULT 0,
    total_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS steps (
    step_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    step_index INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    analysis TEXT,
    observation TEXT,
    error TEXT,
    task_complete INTEGER NOT NULL DEFAULT 0,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    planner_duration_ms INTEGER NOT NULL DEFAULT 0,
    is_copied_context INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    step_id TEXT NOT NULL REFERENCES steps(step_id),
    keystrokes TEXT NOT NULL,
    duration REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id);
CREATE INDEX IF NOT EXISTS idx_commands_step_id ON commands(step_id);
"""


def get_db_path() -> Path:
    """Return the path to the SQLite database."""
    return log_dir() / "termiclaw.db"


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Create tables if needed and return a connection."""
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def insert_run(conn: sqlite3.Connection, state: RunState) -> None:
    """Insert a new run record."""
    conn.execute(
        "INSERT OR REPLACE INTO runs (run_id, instruction, status, started_at, tmux_session) "
        "VALUES (?, ?, ?, ?, ?)",
        (state.run_id, state.instruction, state.status, state.started_at, state.tmux_session),
    )
    conn.commit()


def update_run(
    conn: sqlite3.Connection,
    state: RunState,
    *,
    finished_at: str,
    termination_reason: str,
    total_prompt_chars: int = 0,
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    total_cost_usd: float = 0.0,
) -> None:
    """Update a run with final state."""
    conn.execute(
        "UPDATE runs SET status=?, finished_at=?, termination_reason=?, total_steps=?, "
        "total_prompt_chars=?, total_input_tokens=?, total_output_tokens=?, total_cost_usd=? "
        "WHERE run_id=?",
        (
            state.status,
            finished_at,
            termination_reason,
            state.current_step,
            total_prompt_chars,
            total_input_tokens,
            total_output_tokens,
            total_cost_usd,
            state.run_id,
        ),
    )
    conn.commit()


def insert_step(
    conn: sqlite3.Connection,
    run_id: str,
    step: StepRecord,
    *,
    step_index: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    planner_duration_ms: int = 0,
) -> None:
    """Insert a step with its commands."""
    prompt_chars = 0
    for key, val in step.metrics:
        if key == "prompt_chars" and isinstance(val, int):
            prompt_chars = val

    conn.execute(
        "INSERT OR REPLACE INTO steps "
        "(step_id, run_id, step_index, timestamp, source, analysis, observation, error, "
        "task_complete, prompt_chars, input_tokens, output_tokens, cost_usd, "
        "planner_duration_ms, is_copied_context) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            step.step_id,
            run_id,
            step_index,
            step.timestamp,
            step.source,
            step.analysis,
            step.observation,
            step.error,
            int(step.task_complete),
            prompt_chars,
            input_tokens,
            output_tokens,
            cost_usd,
            planner_duration_ms,
            int(step.is_copied_context),
        ),
    )
    for cmd in step.commands:
        conn.execute(
            "INSERT INTO commands (step_id, keystrokes, duration) VALUES (?, ?, ?)",
            (step.step_id, cmd.keystrokes, cmd.duration),
        )
    conn.commit()


_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60


def _format_duration(started_at: str, finished_at: str | None) -> str:
    """Format duration between two ISO timestamps."""
    if not started_at or not finished_at:
        return "-"
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(finished_at)
    except ValueError:
        return "-"
    total_seconds = int((end - start).total_seconds())
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


def list_runs_from_db(conn: sqlite3.Connection) -> list[RunInfo]:
    """List all runs from SQLite, newest first."""
    cursor = conn.execute(
        "SELECT run_id, instruction, status, total_steps, started_at, finished_at, "
        "tmux_session, termination_reason, total_prompt_chars, "
        "total_input_tokens, total_output_tokens, total_cost_usd "
        "FROM runs ORDER BY started_at DESC",
    )
    results: list[RunInfo] = []
    for row in cursor:
        results.append(
            RunInfo(
                run_id=row[0],
                instruction=row[1],
                status=row[2],
                total_steps=row[3],
                started_at=row[4],
                finished_at=row[5] or "",
                tmux_session=row[6],
                termination_reason=row[7] or "",
                prompt_chars=row[8],
                duration=_format_duration(row[4], row[5]),
                input_tokens=row[9],
                output_tokens=row[10],
                cost_usd=row[11],
            ),
        )
    return results


def get_run(conn: sqlite3.Connection, run_id_prefix: str) -> RunInfo | None:
    """Get a single run by ID prefix."""
    cursor = conn.execute(
        "SELECT run_id, instruction, status, total_steps, started_at, finished_at, "
        "tmux_session, termination_reason, total_prompt_chars, "
        "total_input_tokens, total_output_tokens, total_cost_usd "
        "FROM runs WHERE run_id LIKE ? ORDER BY started_at DESC LIMIT 1",
        (run_id_prefix + "%",),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return RunInfo(
        run_id=row[0],
        instruction=row[1],
        status=row[2],
        total_steps=row[3],
        started_at=row[4],
        finished_at=row[5] or "",
        tmux_session=row[6],
        termination_reason=row[7] or "",
        prompt_chars=row[8],
        duration=_format_duration(row[4], row[5]),
        input_tokens=row[9],
        output_tokens=row[10],
        cost_usd=row[11],
    )


def get_steps(
    conn: sqlite3.Connection,
    run_id: str,
) -> list[dict[str, str | int | float | list[dict[str, str | float]]]]:
    """Get all steps for a run with their commands."""
    cursor = conn.execute(
        "SELECT step_id, step_index, timestamp, source, analysis, observation, error, "
        "task_complete, input_tokens, output_tokens, cost_usd, planner_duration_ms "
        "FROM steps WHERE run_id=? ORDER BY step_index",
        (run_id,),
    )
    results: list[dict[str, str | int | float | list[dict[str, str | float]]]] = []
    for row in cursor:
        step_id = row[0]
        cmds_cursor = conn.execute(
            "SELECT keystrokes, duration FROM commands WHERE step_id=?",
            (step_id,),
        )
        commands: list[dict[str, str | float]] = [
            {"keystrokes": c[0], "duration": c[1]} for c in cmds_cursor
        ]
        results.append(
            {
                "step_id": step_id,
                "step_index": row[1],
                "timestamp": row[2],
                "source": row[3],
                "analysis": row[4] or "",
                "observation": row[5] or "",
                "error": row[6] or "",
                "task_complete": row[7],
                "input_tokens": row[8],
                "output_tokens": row[9],
                "cost_usd": row[10],
                "planner_duration_ms": row[11],
                "commands": commands,
            },
        )
    return results


def get_usage_summary(conn: sqlite3.Connection) -> dict[str, int | float]:
    """Get aggregate usage stats."""
    cursor = conn.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), "
        "COALESCE(SUM(total_steps), 0), "
        "COALESCE(SUM(total_prompt_chars), 0), "
        "COALESCE(SUM(total_input_tokens), 0), "
        "COALESCE(SUM(total_output_tokens), 0), "
        "COALESCE(SUM(total_cost_usd), 0.0) "
        "FROM runs",
    )
    row = cursor.fetchone()
    if not row:
        return {}
    return {
        "total_runs": row[0],
        "succeeded": row[1] or 0,
        "failed": row[2] or 0,
        "total_steps": row[3],
        "total_prompt_chars": row[4],
        "total_input_tokens": row[5],
        "total_output_tokens": row[6],
        "total_cost_usd": row[7],
    }
