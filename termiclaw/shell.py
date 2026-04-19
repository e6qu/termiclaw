"""Imperative shell: `apply(cmd, ports, *, state, run_dir, config) -> Event`.

Dispatches a `Command` through `Ports`, performs the side effect, and
returns the single `Event` that the functional core will consume next.
Errors raised by ports become `*FailedEvent` variants; nothing else
escapes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from termiclaw.commands import (
    ForceInterruptCmd,
    LogStepCmd,
    ObserveCmd,
    QueryPlannerCmd,
    RefreshArtifactsCmd,
    SendKeysCmd,
    SubmitSummarizationCmd,
)
from termiclaw.errors import (
    ArtifactRefreshError,
    ContainerError,
    PlannerError,
)
from termiclaw.events import (
    ArtifactsRefreshed,
    ArtifactsRefreshFailedEvent,
    CommandAcked,
    LoopTick,
    ObservationCaptured,
    PlannerFailedEvent,
    PlannerResponded,
    SendKeysFailed,
    StepLogged,
)
from termiclaw.result import Err

if TYPE_CHECKING:
    from pathlib import Path

    from termiclaw.commands import Command
    from termiclaw.events import Event
    from termiclaw.models import Config
    from termiclaw.ports import Ports
    from termiclaw.state import State


def apply(  # noqa: PLR0911 — one branch per Command variant
    cmd: Command,
    ports: Ports,
    *,
    state: State,
    run_dir: Path,
    config: Config,
) -> Event:
    """Dispatch a command, perform the side effect, return the resulting event."""
    match cmd:
        case ObserveCmd():
            return _apply_observe(ports, state)
        case SendKeysCmd(keystrokes=keystrokes, max_seconds=max_seconds):
            return _apply_send_keys(ports, state, keystrokes, max_seconds, config)
        case ForceInterruptCmd(reason=reason):
            return _apply_force_interrupt(ports, state, reason, config)
        case QueryPlannerCmd(
            prompt=prompt,
            first_call=first_call,
            resume_parent=resume_parent,
            fork_session=fork_session,
        ):
            return _apply_query_planner(
                ports,
                state,
                prompt,
                config,
                first_call=first_call,
                resume_parent=resume_parent,
                fork_session=fork_session,
            )
        case SubmitSummarizationCmd(job=job):
            ports.summarize.submit(job)
            return LoopTick(summarize_ready=False, session_alive=True)
        case RefreshArtifactsCmd(trigger=trigger):
            return _apply_refresh_artifacts(ports, state, run_dir, trigger, config)
        case LogStepCmd(step=step, usage=usage):
            ports.persistence.append_step(run_dir, step)
            ports.persistence.insert_step(
                state.run_id,
                step,
                step_index=state.current_step,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=usage.cost_usd,
                planner_duration_ms=usage.duration_ms,
            )
            return StepLogged(step=step)


def _apply_observe(ports: Ports, state: State) -> ObservationCaptured:
    text, next_buffer = ports.container.get_incremental_output(
        state.container_id,
        state.tmux_session,
        state.previous_buffer,
    )
    return ObservationCaptured(text=text, next_buffer=next_buffer)


def _apply_send_keys(
    ports: Ports,
    state: State,
    keystrokes: str,
    max_seconds: float,
    config: Config,
) -> CommandAcked | SendKeysFailed:
    try:
        ok = ports.container.send_and_wait_idle(
            state.container_id,
            state.tmux_session,
            keystrokes,
            max_seconds=max_seconds,
            poll_interval=config.blocking_poll_interval,
            max_command_length=config.max_command_length,
        )
    except ContainerError as e:
        return SendKeysFailed(error=e)
    return CommandAcked(blocked_ok=ok)


def _apply_force_interrupt(
    ports: Ports,
    state: State,
    reason: str,
    config: Config,
) -> CommandAcked | SendKeysFailed:
    _ = reason
    try:
        ports.container.send_keys(
            state.container_id,
            state.tmux_session,
            "C-c",
            max_command_length=config.max_command_length,
        )
    except ContainerError as e:
        return SendKeysFailed(error=e)
    return CommandAcked(blocked_ok=True)


def _apply_query_planner(  # noqa: PLR0913 — mirrors upstream
    ports: Ports,
    state: State,
    prompt: str,
    config: Config,
    *,
    first_call: bool,
    resume_parent: str | None,
    fork_session: bool,
) -> PlannerResponded | PlannerFailedEvent:
    result = ports.planner.query(
        prompt,
        timeout=config.planner_timeout,
        retries=config.planner_retries,
        claude_session_id=state.claude_session_id,
        first_call=first_call,
        resume_parent=resume_parent,
        fork_session=fork_session,
    )
    if isinstance(result, Err):
        return PlannerFailedEvent(error=result.error)
    raw = result.value
    parsed = ports.planner.parse_response(raw)
    if isinstance(parsed, Err):
        return PlannerFailedEvent(error=PlannerError(str(parsed.error)))
    usage = ports.planner.extract_usage(raw)
    return PlannerResponded(parsed=parsed.value, usage=usage)


def _apply_refresh_artifacts(
    ports: Ports,
    state: State,
    run_dir: Path,
    trigger: str,
    config: Config,
) -> ArtifactsRefreshed | ArtifactsRefreshFailedEvent:
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
        raw = result.value
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if isinstance(envelope, dict):
            value = envelope.get("result", raw)
            return str(value) if value is not None else raw
        return raw

    try:
        ports.artifacts.refresh(state, run_dir, query_fn=query_fn)
    except ArtifactRefreshError as e:
        return ArtifactsRefreshFailedEvent(error=e)
    return ArtifactsRefreshed(trigger=trigger)
