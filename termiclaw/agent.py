"""Main observe-decide-act loop."""

from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from termiclaw import db, planner, summarizer, tmux, trajectory
from termiclaw.logging import get_logger, setup_logging
from termiclaw.models import Config, ParseResult, PlannerUsage, RunState, StepRecord

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

_log = get_logger("agent")

_MAX_RECENT_STEPS = 20


def run(config: Config) -> RunState:
    """Run the full agent loop. Top-level entry point."""
    run_id = uuid.uuid4().hex
    session_name = f"termiclaw-{run_id[:8]}"
    now = datetime.now(tz=UTC).isoformat()

    level = logging.DEBUG if config.verbose else logging.INFO
    setup_logging(run_id, level=level)
    _log.info("Starting run", extra={"run_id": run_id, "instruction": config.instruction})

    run_dir = trajectory.ensure_run_dir(config.runs_dir, run_id)
    conn = db.init_db()
    state = RunState(
        run_id=run_id,
        instruction=config.instruction,
        tmux_session=session_name,
        started_at=now,
        status="active",
        max_turns=config.max_turns,
    )
    db.insert_run(conn, state)

    try:
        tmux.provision_session(
            session_name,
            width=config.pane_width,
            height=config.pane_height,
            history_limit=config.history_limit,
        )
        time.sleep(0.5)
    except subprocess.CalledProcessError:
        _log.error("Failed to provision tmux session")
        state.status = "failed"
        finished = datetime.now(tz=UTC).isoformat()
        trajectory.write_run_metadata(
            run_dir,
            state,
            finished_at=finished,
            termination_reason="tmux_provision_failed",
        )
        db.update_run(conn, state, finished_at=finished, termination_reason="tmux_provision_failed")
        conn.close()
        _log.info("Run finished", extra={"status": state.status, "steps": state.current_step})
        return state

    try:
        _run_loop(state, config, run_dir, conn)
    except KeyboardInterrupt:
        _log.info("Interrupted by user")
        state.status = "cancelled"
    finally:
        finished = datetime.now(tz=UTC).isoformat()
        reason = _termination_reason(state)
        trajectory.write_run_metadata(
            run_dir,
            state,
            finished_at=finished,
            termination_reason=reason,
        )
        usage = _get_run_usage(conn, state.run_id)
        db.update_run(
            conn,
            state,
            finished_at=finished,
            termination_reason=reason,
            total_prompt_chars=state.total_prompt_chars,
            total_input_tokens=usage.input_tokens,
            total_output_tokens=usage.output_tokens,
            total_cost_usd=usage.cost_usd,
        )
        conn.close()
        if not config.keep_session:
            tmux.destroy_session(session_name)
        _log.info("Run finished", extra={"status": state.status, "steps": state.current_step})

    return state


def _get_run_usage(conn: sqlite3.Connection, run_id: str) -> PlannerUsage:
    """Aggregate usage from steps table for a run."""
    cursor = conn.execute(
        "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
        "COALESCE(SUM(cost_usd),0.0) FROM steps WHERE run_id=?",
        (run_id,),
    )
    row = cursor.fetchone()
    if not row:
        return PlannerUsage()
    return PlannerUsage(input_tokens=row[0], output_tokens=row[1], cost_usd=row[2])


def _run_loop(state: RunState, config: Config, run_dir: Path, conn: sqlite3.Connection) -> None:
    """The main observe-decide-act loop."""
    prompt = ""

    for _episode in range(config.max_turns):
        if not tmux.is_session_alive(state.tmux_session):
            _log.warning("tmux session died")
            state.status = "failed"
            break

        _maybe_summarize(state, config, run_dir)

        full_prompt = planner.build_prompt(
            config.instruction,
            prompt or "Shell is ready.",
            state.summary,
            state.qa_context,
        )
        state.total_prompt_chars += len(full_prompt)

        try:
            raw = planner.query_planner(
                full_prompt,
                timeout=config.planner_timeout,
                retries=config.planner_retries,
            )
        except RuntimeError:
            _log.warning("Planner query failed after retries")
            error_step = StepRecord(
                step_id=uuid.uuid4().hex,
                timestamp=datetime.now(tz=UTC).isoformat(),
                source="error",
                observation=prompt,
                error="Planner failed after retries",
            )
            trajectory.append_step(run_dir, error_step)
            db.insert_step(conn, state.run_id, error_step, step_index=state.current_step)
            _track_step(state, error_step)
            prompt = "The planner failed to respond. Please try again."
            continue

        usage = planner.extract_usage(raw)
        parsed = planner.parse_response(raw)

        if parsed.error:
            _handle_parse_error(state, parsed, run_dir, prompt, conn=conn, usage=usage)
            prompt = (
                f"Previous response had parsing errors:\n{parsed.error}\n\n"
                "Please fix these issues and respond with valid JSON."
            )
            continue

        if parsed.task_complete:
            done = _handle_completion(state, parsed, run_dir, prompt, conn=conn, usage=usage)
            if done:
                break
            visible = tmux.capture_visible(state.tmux_session)
            prompt = (
                f"{visible}\n\n"
                "IMPORTANT: You previously indicated task_complete=true. "
                "If the task is truly done, respond with task_complete=true again to confirm. "
                "If you need to do more work, set task_complete=false and provide commands."
            )
            continue

        state.pending_completion = False
        _execute_commands(state, config, parsed)

        output, state.previous_buffer = tmux.get_incremental_output(
            state.tmux_session,
            state.previous_buffer,
        )
        output = tmux.truncate_output(output, max_bytes=config.max_output_bytes)

        _log_step(state, output, parsed, run_dir, conn=conn, usage=usage)
        prompt = output

    else:
        state.status = "failed"
        _log.warning("Max turns reached")


def _handle_parse_error(
    state: RunState,
    parsed: ParseResult,
    run_dir: Path,
    observation: str,
    *,
    conn: sqlite3.Connection | None = None,
    usage: PlannerUsage | None = None,
) -> None:
    """Log a parse error step."""
    _log.warning("Parse error", extra={"error": parsed.error})
    step = StepRecord(
        step_id=uuid.uuid4().hex,
        timestamp=datetime.now(tz=UTC).isoformat(),
        source="error",
        observation=observation,
        error=parsed.error,
    )
    trajectory.append_step(run_dir, step)
    if conn:
        u = usage or PlannerUsage()
        db.insert_step(
            conn,
            state.run_id,
            step,
            step_index=state.current_step,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cost_usd=u.cost_usd,
            planner_duration_ms=u.duration_ms,
        )
    _track_step(state, step)


def _handle_completion(
    state: RunState,
    parsed: ParseResult,
    run_dir: Path,
    observation: str,
    *,
    conn: sqlite3.Connection | None = None,
    usage: PlannerUsage | None = None,
) -> bool:
    """Handle task_complete. Returns True if confirmed (break loop)."""
    if state.pending_completion:
        state.status = "succeeded"
        _log.info("Task completed (confirmed)")
        step = StepRecord(
            step_id=uuid.uuid4().hex,
            timestamp=datetime.now(tz=UTC).isoformat(),
            source="agent",
            observation=observation,
            analysis=parsed.analysis,
            plan=parsed.plan,
            task_complete=True,
        )
        trajectory.append_step(run_dir, step)
        if conn:
            u = usage or PlannerUsage()
            db.insert_step(
                conn,
                state.run_id,
                step,
                step_index=state.current_step,
                input_tokens=u.input_tokens,
                output_tokens=u.output_tokens,
                cost_usd=u.cost_usd,
                planner_duration_ms=u.duration_ms,
            )
        _track_step(state, step)
        return True

    state.pending_completion = True
    _log.info("Task completion pending confirmation")
    return False


def _execute_commands(state: RunState, config: Config, parsed: ParseResult) -> None:
    """Execute parsed commands against tmux."""
    if not parsed.commands:
        return
    for cmd in parsed.commands:
        tmux.send_keys(state.tmux_session, cmd.keystrokes)
        wait = min(cmd.duration, config.max_duration)
        time.sleep(wait)
    time.sleep(config.min_delay)


def _maybe_summarize(state: RunState, config: Config, run_dir: Path) -> None:
    """Check and run summarization if needed."""
    if not summarizer.should_summarize(state.total_prompt_chars, config.summarization_threshold):
        return

    _log.info("Triggering summarization", extra={"prompt_chars": state.total_prompt_chars})
    visible = tmux.capture_visible(state.tmux_session)
    recent_text = summarizer.format_steps_text(state.recent_steps)
    if not recent_text:
        recent_text = f"[{state.current_step} steps completed]"
    full_text = trajectory.read_trajectory_text(run_dir)
    if not full_text:
        full_text = recent_text

    def query_fn(prompt: str) -> str:
        raw = planner.query_planner(prompt, timeout=config.planner_timeout, retries=1)
        try:
            envelope = json.loads(raw)
            return str(envelope.get("result", raw))
        except (json.JSONDecodeError, TypeError):
            return raw

    summary, qa = summarizer.summarize_with_fallback(
        state.instruction,
        recent_text,
        full_text,
        visible,
        query_fn,
    )
    state.summary = summary
    state.qa_context = qa
    state.total_prompt_chars = 0
    state.recent_steps.clear()

    step = StepRecord(
        step_id=uuid.uuid4().hex,
        timestamp=datetime.now(tz=UTC).isoformat(),
        source="system",
        observation="Summarization checkpoint created",
        is_copied_context=True,
    )
    trajectory.append_step(run_dir, step)
    _track_step(state, step)


def _log_step(
    state: RunState,
    observation: str,
    parsed: ParseResult,
    run_dir: Path,
    *,
    conn: sqlite3.Connection | None = None,
    usage: PlannerUsage | None = None,
) -> None:
    """Log a normal step."""
    step = StepRecord(
        step_id=uuid.uuid4().hex,
        timestamp=datetime.now(tz=UTC).isoformat(),
        source="agent",
        observation=observation,
        analysis=parsed.analysis,
        plan=parsed.plan,
        commands=parsed.commands,
        metrics=(("prompt_chars", state.total_prompt_chars),),
    )
    trajectory.append_step(run_dir, step)
    if conn:
        u = usage or PlannerUsage()
        db.insert_step(
            conn,
            state.run_id,
            step,
            step_index=state.current_step,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cost_usd=u.cost_usd,
            planner_duration_ms=u.duration_ms,
        )
    _track_step(state, step)
    _log.info("Step completed", extra={"step": state.current_step})


def _track_step(state: RunState, step: StepRecord) -> None:
    """Track step in recent history and increment counter."""
    state.recent_steps.append(step)
    state.recent_steps = state.recent_steps[-_MAX_RECENT_STEPS:]
    state.current_step += 1


def _termination_reason(state: RunState) -> str:
    """Derive termination reason from run state."""
    if state.status == "succeeded":
        return "task_complete_confirmed"
    if state.status == "cancelled":
        return "keyboard_interrupt"
    return "max_turns_or_failure"
