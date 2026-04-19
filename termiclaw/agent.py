"""Top-level agent run: thin imperative shell over `decide` + `apply`.

Responsible for provisioning the container, building the Ports bundle,
driving the decide/apply loop, and tearing down. No decision logic,
no step-building, no stall handling — all of that lives in
`termiclaw.decide` (pure) and `termiclaw.shell` (per-command effect).
"""

from __future__ import annotations

import json
import logging
import subprocess
import uuid
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from termiclaw import agent_core, db, trajectory
from termiclaw.decide import DecideEffects, decide
from termiclaw.errors import TermiclawError
from termiclaw.events import (
    LoopTick,
    SummarizationDone,
    SummarizationFailedEvent,
)
from termiclaw.logging import get_logger, setup_logging
from termiclaw.result import Err, Ok
from termiclaw.runtime import build_default_ports
from termiclaw.shell import apply
from termiclaw.state import ForkContext, State, with_status

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from termiclaw.errors import PlannerError
    from termiclaw.events import Event
    from termiclaw.models import Config
    from termiclaw.ports import Ports
    from termiclaw.result import Result
    from termiclaw.summarize_worker import (
        SummarizationComplete,
        SummarizationError,
    )

_log = get_logger("agent")


class _StateHolder:
    """Mutable one-cell handle shared with long-lived worker closures.

    The summarization query_fn captures this holder and reads
    `holder.state.claude_session_id` each invocation so post-fork
    session-id adoption is picked up.
    """

    __slots__ = ("state",)

    def __init__(self, state: State) -> None:
        self.state = state


def run(
    config: Config,
    *,
    parent: State | None = None,
    ports: Ports | None = None,
) -> State:
    """Run the full agent loop. Top-level entry point."""
    run_id = uuid.uuid4().hex
    session_name = f"termiclaw-{run_id[:8]}"
    now_iso = datetime.now(tz=UTC).isoformat()

    level = logging.DEBUG if config.verbose else logging.INFO
    setup_logging(run_id, level=level)
    _log.info("Starting run", extra={"run_id": run_id, "instruction": config.instruction})

    run_dir = trajectory.ensure_run_dir(config.runs_dir, run_id)
    conn = db.init_db()

    fork = (
        ForkContext(
            parent_run_id=parent.run_id,
            forked_at_step=parent.current_step,
            resume_parent_session=parent.claude_session_id,
        )
        if parent is not None
        else None
    )
    state = State(
        run_id=run_id,
        instruction=config.instruction,
        tmux_session=session_name,
        started_at=now_iso,
        status="active",
        max_turns=config.max_turns,
        claude_session_id=str(uuid.uuid4()),
        fork=fork,
    )

    holder = _StateHolder(state)
    from termiclaw import planner  # noqa: PLC0415 — avoid circular import

    ports_resolved = ports or build_default_ports(
        config,
        conn,
        _build_summarization_query_fn(holder, config, planner.query_planner),
    )

    image_result = ports_resolved.container.ensure_image()
    if isinstance(image_result, Err):
        return _provision_failure(
            state,
            run_dir,
            ports_resolved,
            f"image build failed: {image_result.error}",
        )
    provision_result = ports_resolved.container.provision_container(
        image_result.value,
        config.docker_network,
    )
    if isinstance(provision_result, Err):
        return _provision_failure(
            state,
            run_dir,
            ports_resolved,
            f"container provision failed: {provision_result.error}",
        )
    state = replace(state, container_id=provision_result.value)
    holder.state = state
    try:
        ports_resolved.container.provision_session(
            state.container_id,
            session_name,
            width=config.pane_width,
            height=config.pane_height,
            history_limit=config.history_limit,
        )
    except subprocess.CalledProcessError:
        _log.exception("Failed to provision tmux session inside container")
        return _provision_failure(state, run_dir, ports_resolved, "tmux session provision failed")

    ports_resolved.persistence.insert_run(state)
    effects = DecideEffects(
        new_id=lambda: uuid.uuid4().hex,
        now=lambda: datetime.now(tz=UTC).isoformat(),
    )

    try:
        state = _run_turns(state, config, run_dir, ports_resolved, effects, holder)
    except KeyboardInterrupt:
        _log.info("Interrupted by user")
        state = with_status(state, "cancelled")
    finally:
        ports_resolved.summarize.shutdown()
        finished = datetime.now(tz=UTC).isoformat()
        reason = agent_core.termination_reason(state.status)
        state = _final_artifact_snapshot(state, config, run_dir, ports_resolved)
        ports_resolved.persistence.write_run_metadata(
            run_dir,
            state,
            finished_at=finished,
            termination_reason=reason,
        )
        usage = ports_resolved.persistence.aggregate_usage(state.run_id)
        ports_resolved.persistence.update_run(
            state,
            finished_at=finished,
            termination_reason=reason,
            total_prompt_tokens=state.total_prompt_tokens,
            total_input_tokens=usage.input_tokens,
            total_output_tokens=usage.output_tokens,
            total_cost_usd=usage.cost_usd,
        )
        conn.close()
        if not config.keep_session:
            ports_resolved.container.destroy_container(state.container_id)
        _log.info("Run finished", extra={"status": state.status, "steps": state.current_step})

    return state


def _run_turns(
    state: State,
    config: Config,
    run_dir: Path,
    ports: Ports,
    effects: DecideEffects,
    holder: _StateHolder,
) -> State:
    """Drive up to `state.max_turns` top-level ticks."""
    for _ in range(state.max_turns):
        holder.state = state
        session_alive = ports.container.is_session_alive(
            state.container_id,
            state.tmux_session,
        )
        polled = ports.summarize.poll()
        event: Event = (
            _event_from_poll(polled)
            if polled is not None
            else LoopTick(
                summarize_ready=ports.summarize.idle() and session_alive,
                session_alive=session_alive,
            )
        )
        state = _drive(state, event, config, run_dir, ports, effects, holder)
        if state.status != "active":
            return state
    _log.warning("Max turns reached")
    return with_status(state, "failed")


def _drive(
    state: State,
    initial_event: Event,
    config: Config,
    run_dir: Path,
    ports: Ports,
    effects: DecideEffects,
    holder: _StateHolder,
) -> State:
    """Decide → apply → decide chain. Runs until the command queue is empty.

    Commands emitted by a decide call that transitions the run out of
    `"active"` (e.g., the terminal `LogStepCmd` from confirmed
    completion) are still applied *and* re-decided so state bookkeeping
    (step counter, etc.) catches the last event. Only the *new* commands
    produced by that terminal re-decide are dropped, since further
    Observe/Query would spin forever.
    """
    transition = decide(state, initial_event, config, effects)
    state = transition.state
    holder.state = state
    pending = deque(transition.commands)

    while pending:
        was_active = state.status == "active"
        cmd = pending.popleft()
        event = apply(cmd, ports, state=state, run_dir=run_dir, config=config)
        sub = decide(state, event, config, effects)
        state = sub.state
        holder.state = state
        # Always re-decide so terminal events (e.g. StepLogged from the
        # final LogStepCmd emitted by confirmed completion) bump the step
        # counter and apply other bookkeeping (see BUG-41). The gate
        # below is about whether *new* commands should queue: if the run
        # was already terminal when we applied this command, further
        # Observe/Query would spin forever — drop them. If the run was
        # active and just transitioned (its own decide emitted terminal
        # cleanup commands), we must keep them so the final step lands.
        if was_active:
            pending.extend(sub.commands)
    return state


def _event_from_poll(
    polled: Result[SummarizationComplete, SummarizationError],
) -> Event:
    """Map a worker.poll() result to the corresponding Event variant."""
    if isinstance(polled, Ok):
        return SummarizationDone(
            summary=polled.value.summary,
            qa_context=polled.value.qa_context,
        )
    return SummarizationFailedEvent(error=polled.error)


def _provision_failure(
    state: State,
    run_dir: Path,
    ports: Ports,
    reason: str,
) -> State:
    """Short-circuit tear-down when container/session provisioning fails."""
    _log.error("Provisioning failed", extra={"reason": reason})
    state = with_status(state, "failed")
    finished = datetime.now(tz=UTC).isoformat()
    ports.persistence.write_run_metadata(
        run_dir,
        state,
        finished_at=finished,
        termination_reason="container_provision_failed",
    )
    ports.persistence.update_run(
        state,
        finished_at=finished,
        termination_reason="container_provision_failed",
        total_prompt_tokens=state.total_prompt_tokens,
        total_input_tokens=0,
        total_output_tokens=0,
        total_cost_usd=0.0,
    )
    ports.summarize.shutdown()
    if state.container_id:
        ports.container.destroy_container(state.container_id)
    _log.info("Run finished", extra={"status": state.status, "steps": state.current_step})
    return state


def _final_artifact_snapshot(
    state: State,
    config: Config,
    run_dir: Path,
    ports: Ports,
) -> State:
    """Refresh artifacts one last time before teardown, best-effort."""
    if state.current_step == 0:
        return state
    if not ports.container.is_session_alive(state.container_id, state.tmux_session):
        return state

    def query_fn(prompt: str) -> str:
        result = ports.planner.query(
            prompt,
            timeout=config.planner_timeout,
            retries=1,
            claude_session_id=state.claude_session_id,
            first_call=False,
            resume_parent=None,
            fork_session=False,
        )
        if isinstance(result, Err):
            raise result.error
        try:
            envelope = json.loads(result.value)
        except (json.JSONDecodeError, TypeError):
            return result.value
        if isinstance(envelope, dict):
            return str(envelope.get("result", ""))
        return ""

    try:
        ports.artifacts.refresh(state, run_dir, query_fn=query_fn)
    except TermiclawError:
        _log.exception("Final artifact snapshot failed")
    return state


def _build_summarization_query_fn(
    holder: _StateHolder,
    config: Config,
    query_planner: Callable[..., Result[str, PlannerError]],
) -> Callable[[str], str]:
    """Build the `query_fn` the background summarizer uses for its 3 subagents.

    `query_planner` is injected (rather than imported inline) so tests can
    pass a fake without `mock.patch("termiclaw.planner.query_planner", ...)`.
    Production callers pass `termiclaw.planner.query_planner` via the
    inline import in `agent.run`.
    """

    def query_fn(prompt: str) -> str:
        result = query_planner(
            prompt,
            timeout=config.planner_timeout,
            retries=1,
            claude_session_id=holder.state.claude_session_id,
            first_call=False,
        )
        if isinstance(result, Err):
            raise result.error
        raw = result.value
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if isinstance(envelope, dict):
            value = envelope.get("result", raw)
            return str(value) if value is not None else raw
        return raw

    return query_fn
