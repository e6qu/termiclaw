"""Pure decision core: `decide(state, event, config, effects) -> Transition`.

No I/O. No subprocess. No sleep. No logging except the stdlib logger
(which is a write-through sink — fine for determinism because it's the
same sink regardless of input). `decide` returns the next `State` and
the commands the shell should apply next. IDs and timestamps are drawn
from `DecideEffects` so tests can seed them deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from termiclaw import agent_core, planner, summarizer
from termiclaw.commands import (
    LogStepCmd,
    ObserveCmd,
    QueryPlannerCmd,
    RefreshArtifactsCmd,
    SendKeysCmd,
    SubmitSummarizationCmd,
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
    SessionDiedEvent,
    StepLogged,
    SummarizationDone,
    SummarizationFailedEvent,
)
from termiclaw.models import PlannerUsage, StepRecord
from termiclaw.stall import StallSignal
from termiclaw.state import (
    with_stall,
    with_stall_counters,
    with_status,
    with_step,
    with_summarization,
)
from termiclaw.summarize_worker import SummarizationJob
from termiclaw.transitions import Transition

if TYPE_CHECKING:
    from collections.abc import Callable

    from termiclaw.commands import Command
    from termiclaw.errors import (
        ArtifactRefreshError,
        ContainerError,
        PlannerError,
        SummarizationError,
    )
    from termiclaw.events import Event
    from termiclaw.models import Config, ParseResult
    from termiclaw.state import State


@dataclass(frozen=True, slots=True)
class DecideEffects:
    """Deterministic sources decide needs: ID generator + clock."""

    new_id: Callable[[], str]
    now: Callable[[], str]


def decide(  # noqa: C901, PLR0911 — one branch per Event variant
    state: State,
    event: Event,
    config: Config,
    effects: DecideEffects,
) -> Transition:
    """Pure transition: (state, event, config, effects) → new state + commands."""
    match event:
        case LoopTick(summarize_ready=ready, session_alive=alive):
            return _on_loop_tick(state, config, effects, summarize_ready=ready, session_alive=alive)
        case ObservationCaptured(text=text, next_buffer=buf):
            return _on_observation(state, text, buf, config, effects)
        case PlannerResponded(parsed=parsed, usage=usage):
            return _on_planner_responded(state, parsed, usage, config, effects)
        case PlannerFailedEvent(error=err):
            return _on_planner_failed(state, err, effects)
        case CommandAcked(blocked_ok=ok):
            return _on_command_acked(state, blocked_ok=ok)
        case SendKeysFailed(error=err):
            return _on_send_keys_failed(state, err)
        case SummarizationDone(summary=summary, qa_context=qa):
            return _on_summarization_done(state, summary, qa, effects)
        case SummarizationFailedEvent(error=err):
            return _on_summarization_failed(state, err)
        case ArtifactsRefreshed(trigger=trigger):
            return _on_artifacts_refreshed(state, trigger, effects)
        case ArtifactsRefreshFailedEvent(error=err):
            return _on_artifacts_refresh_failed(state, err)
        case StepLogged(step=step):
            return Transition(state=with_step(state, step))
        case SessionDiedEvent():
            return Transition(state=with_status(state, "failed"))


def _on_loop_tick(
    state: State,
    config: Config,
    effects: DecideEffects,
    *,
    summarize_ready: bool,
    session_alive: bool,
) -> Transition:
    """Top-of-iteration dispatch: artifacts, summarization, observe."""
    if not session_alive:
        return Transition(state=with_status(state, "failed"))
    trigger = agent_core.artifact_refresh_trigger(state, config)
    if trigger:
        return Transition(state=state, commands=(RefreshArtifactsCmd(trigger=trigger),))
    commands: tuple[Command, ...] = ()
    if summarize_ready and agent_core.should_summarize(state, config):
        job = _build_summarization_job(state)
        commands = (*commands, SubmitSummarizationCmd(job=job))
    commands = (*commands, ObserveCmd())
    _ = effects
    return Transition(state=state, commands=commands)


def _on_observation(
    state: State,
    text: str,
    next_buffer: str,
    config: Config,
    effects: DecideEffects,
) -> Transition:
    """After a terminal diff: apply timeout banner, emit planner query."""
    _ = effects
    truncated_buffer = (
        next_buffer[-config.capture_tail_bytes :]
        if len(
            next_buffer,
        )
        > config.capture_tail_bytes
        else next_buffer
    )
    state = replace(state, previous_buffer=truncated_buffer)

    if state.pending_blocking_timeout:
        text = agent_core.format_blocking_timeout_notice(config) + text
        state = replace(state, pending_blocking_timeout=False)

    # Stash the (post-banner) observation so the next PlannerResponded
    # can log it onto the StepRecord. Without this, trajectory steps
    # ship `terminal_output=""` — see BUG-43.
    state = replace(state, last_observation=text)

    prompt = _build_planner_prompt(state, text, config)
    resume_parent = (
        state.fork.resume_parent_session if state.fork is not None and state.is_first_call else None
    )
    return Transition(
        state=state,
        commands=(
            QueryPlannerCmd(
                prompt=prompt,
                first_call=state.is_first_call,
                resume_parent=resume_parent,
                fork_session=resume_parent is not None,
            ),
        ),
    )


def _on_planner_responded(
    state: State,
    parsed: ParseResult,
    usage: PlannerUsage,
    config: Config,
    effects: DecideEffects,
) -> Transition:
    """Parsed planner output: completion, commands, or empty-response logging."""
    new_tokens = state.total_prompt_tokens + usage.input_tokens + usage.cache_read_input_tokens
    new_session_id = (
        usage.claude_session_id
        if state.is_first_call and usage.claude_session_id
        else state.claude_session_id
    )
    state = replace(
        state,
        total_prompt_tokens=new_tokens,
        claude_session_id=new_session_id,
        is_first_call=False,
        fork=None if state.fork is not None else state.fork,
        consecutive_planner_failures=0,
    )

    if parsed.task_complete:
        return _handle_completion(state, parsed, usage, config, effects)

    state = replace(state, pending_completion=False)
    observation = state.last_observation
    state = replace(state, last_observation="")
    if not parsed.commands:
        step = _log_agent_step(state, observation, parsed, effects)
        return Transition(state=state, commands=(LogStepCmd(step=step, usage=usage),))

    commands: tuple[Command, ...] = tuple(
        SendKeysCmd(
            keystrokes=cmd.keystrokes,
            max_seconds=agent_core.clamp_command_wait(cmd, config.blocking_max_seconds),
        )
        for cmd in parsed.commands
    )
    step = _log_agent_step(state, observation, parsed, effects)
    commands = (*commands, LogStepCmd(step=step, usage=usage))
    return Transition(state=state, commands=commands)


def _handle_completion(
    state: State,
    parsed: ParseResult,
    usage: PlannerUsage,
    config: Config,
    effects: DecideEffects,
) -> Transition:
    """Two-phase `task_complete` confirmation."""
    if state.pending_completion:
        observation = state.last_observation
        state = replace(state, last_observation="")
        step = _log_agent_step(state, observation, parsed, effects, task_complete=True)
        state = with_status(state, "succeeded")
        return Transition(state=state, commands=(LogStepCmd(step=step, usage=usage),))
    state = replace(state, pending_completion=True)
    resume_parent = None
    prompt = agent_core.format_completion_confirmation_prompt("")
    _ = config
    return Transition(
        state=state,
        commands=(
            QueryPlannerCmd(
                prompt=prompt,
                first_call=False,
                resume_parent=resume_parent,
                fork_session=False,
            ),
        ),
    )


_MAX_CONSECUTIVE_PLANNER_FAILURES = 3


def _on_planner_failed(
    state: State,
    error: PlannerError,
    effects: DecideEffects,
) -> Transition:
    """Planner query failed: log error step; after N consecutive, fail the run.

    Does *not* emit `ObserveCmd` — that would create a tight inner
    `QueryPlannerCmd → PlannerFailed → ObserveCmd → ObservationCaptured
    → QueryPlannerCmd → …` cycle within a single outer turn. Instead we
    log and let the outer `_run_turns` loop tick a fresh `LoopTick`,
    which consumes one of the `max_turns` budget.

    Also clears `is_first_call` so the next attempt uses `--resume`
    instead of re-asserting `--session-id` (which Claude CLI rejects
    if the id is already reserved from a previous attempt).
    """
    step = _log_error_step(state, f"Planner failed: {error}", effects)
    failures = state.consecutive_planner_failures + 1
    new_state = replace(
        state,
        consecutive_planner_failures=failures,
        is_first_call=False,
    )
    if failures >= _MAX_CONSECUTIVE_PLANNER_FAILURES:
        new_state = with_status(new_state, "failed")
    return Transition(
        state=new_state,
        commands=(LogStepCmd(step=step, usage=_zero_usage()),),
    )


def _on_command_acked(state: State, *, blocked_ok: bool) -> Transition:
    """Keystroke ack: set/clear the blocking-timeout flag; observe again."""
    return Transition(
        state=replace(state, pending_blocking_timeout=not blocked_ok),
        commands=(ObserveCmd(),),
    )


def _on_send_keys_failed(state: State, error: ContainerError) -> Transition:
    """Keystroke send raised — fail the run."""
    _ = error
    return Transition(state=with_status(state, "failed"))


def _on_summarization_done(
    state: State,
    summary: str,
    qa_context: str,
    effects: DecideEffects,
) -> Transition:
    """Worker produced a checkpoint: apply it; log a checkpoint step."""
    state = with_summarization(state, summary, qa_context)
    step = StepRecord(
        step_id=effects.new_id(),
        timestamp=effects.now(),
        source="system",
        observation="Summarization checkpoint created",
        is_copied_context=True,
    )
    return Transition(state=state, commands=(LogStepCmd(step=step, usage=_zero_usage()),))


def _on_summarization_failed(
    state: State,
    error: SummarizationError,
) -> Transition:
    """Summarization worker raised — fail the run."""
    _ = error
    return Transition(state=with_status(state, "failed"))


def _on_artifacts_refreshed(
    state: State,
    trigger: str,
    effects: DecideEffects,
) -> Transition:
    """Artifact write succeeded: log a marker step."""
    step = StepRecord(
        step_id=effects.new_id(),
        timestamp=effects.now(),
        source="system",
        observation=f"Artifacts refreshed (trigger={trigger})",
    )
    return Transition(state=state, commands=(LogStepCmd(step=step, usage=_zero_usage()),))


def _on_artifacts_refresh_failed(
    state: State,
    error: ArtifactRefreshError,
) -> Transition:
    """Artifact refresh raised — fail the run."""
    _ = error
    return Transition(state=with_status(state, "failed"))


def _build_planner_prompt(state: State, observation: str, config: Config) -> str:
    """Delegate to `planner.build_prompt` — pure."""
    _ = config
    return planner.build_prompt(
        state.instruction,
        observation or "Shell is ready.",
        state.summary,
        state.qa_context,
    )


def _build_summarization_job(state: State) -> SummarizationJob:
    """Build a job snapshot from state — called from decide, pure."""
    recent_text = summarizer.format_steps_text(state.recent_steps)
    if not recent_text:
        recent_text = f"[{state.current_step} steps completed]"
    full_text = recent_text  # shell fills real trajectory text post-decide if needed
    return SummarizationJob(
        instruction=state.instruction,
        recent_text=recent_text,
        full_text=full_text,
        visible_screen="",  # shell annotates the actual screen before submit
    )


def _log_agent_step(
    state: State,
    observation: str,
    parsed: ParseResult,
    effects: DecideEffects,
    *,
    task_complete: bool = False,
) -> StepRecord:
    """Compose an agent-source StepRecord with current token tally."""
    return StepRecord(
        step_id=effects.new_id(),
        timestamp=effects.now(),
        source="agent",
        observation=observation,
        analysis=parsed.analysis,
        plan=parsed.plan,
        commands=parsed.commands,
        task_complete=task_complete,
        metrics=(
            ("prompt_tokens", state.total_prompt_tokens),
            ("prompt_version", planner.PROMPT_VERSION),
        ),
    )


def _log_error_step(state: State, message: str, effects: DecideEffects) -> StepRecord:
    """Compose an error-source StepRecord."""
    _ = state
    return StepRecord(
        step_id=effects.new_id(),
        timestamp=effects.now(),
        source="error",
        observation="",
        error=message,
    )


def _zero_usage() -> PlannerUsage:
    return PlannerUsage()


__all__ = [
    "DecideEffects",
    "StallSignal",
    "decide",
    "with_stall",
    "with_stall_counters",
    "with_step",
]
