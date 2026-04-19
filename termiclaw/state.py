"""Frozen run state for the functional-core / imperative-shell split.

The imperative shell (`agent.run()`) threads `State` through `decide` →
`apply` cycles. Every mutation goes through `dataclasses.replace` or one
of the `with_*` helpers in this module — there is no in-place state
update anywhere in the codebase.

`State` replaces the v1.3 `models.RunState` (deleted); `StallState` moved
here too. `ForkContext` is a new immutable bundle for fork-specific
metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from termiclaw.models import StepRecord


type RunStatus = Literal["active", "succeeded", "failed", "cancelled"]


def coerce_status(status: str) -> RunStatus:
    """Narrow a raw (SQLite-loaded) status string to the RunStatus union."""
    if status == "active":
        return "active"
    if status == "succeeded":
        return "succeeded"
    if status == "cancelled":
        return "cancelled"
    return "failed"


@dataclass(frozen=True, slots=True)
class ForkContext:
    """Fork metadata. Present iff the run descends from another."""

    parent_run_id: str
    forked_at_step: int
    resume_parent_session: str


@dataclass(frozen=True, slots=True)
class StallState:
    """Rolling counters for stall detection."""

    identical_obs_streak: int = 0
    repeat_command_streak: int = 0
    last_keystrokes_hash: str = ""
    last_observation_hash: str = ""
    nudges_sent: int = 0
    forced_interrupts: int = 0


@dataclass(frozen=True, slots=True)
class State:
    """Every field needed by decide/apply; immutable — replace via helpers."""

    run_id: str
    instruction: str
    tmux_session: str
    started_at: str
    status: RunStatus = "active"
    container_id: str = ""
    claude_session_id: str = ""
    max_turns: int = 1_000_000
    fork: ForkContext | None = None
    current_step: int = 0
    previous_buffer: str = ""
    summary: str | None = None
    qa_context: str | None = None
    total_prompt_tokens: int = 0
    recent_steps: tuple[StepRecord, ...] = ()
    stall: StallState = field(default_factory=StallState)
    pending_completion: bool = False
    pending_blocking_timeout: bool = False
    is_first_call: bool = True
    consecutive_planner_failures: int = 0
    last_observation: str = ""


_DEFAULT_MAX_RECENT = 20


def with_step(
    state: State,
    step: StepRecord,
    *,
    max_recent: int = _DEFAULT_MAX_RECENT,
) -> State:
    """Append a step and bump `current_step`. Ring-buffer trims old entries."""
    new_recent = (*state.recent_steps, step)[-max_recent:]
    return replace(
        state,
        current_step=state.current_step + 1,
        recent_steps=new_recent,
    )


def with_status(state: State, status: RunStatus) -> State:
    """Transition the run's lifecycle status."""
    return replace(state, status=status)


def with_summarization(state: State, summary: str, qa_context: str) -> State:
    """Apply a completed summarization: reset the token budget and recent steps."""
    return replace(
        state,
        summary=summary,
        qa_context=qa_context,
        total_prompt_tokens=0,
        recent_steps=(),
    )


def with_stall_counters(  # noqa: PLR0913 — discrete field knobs; all kw-only
    state: State,
    *,
    identical_obs_streak: int | None = None,
    repeat_command_streak: int | None = None,
    last_keystrokes_hash: str | None = None,
    last_observation_hash: str | None = None,
    nudges_sent: int | None = None,
    forced_interrupts: int | None = None,
) -> State:
    """Update any subset of StallState fields. None means keep existing."""
    updates: dict[str, int | str] = {}
    if identical_obs_streak is not None:
        updates["identical_obs_streak"] = identical_obs_streak
    if repeat_command_streak is not None:
        updates["repeat_command_streak"] = repeat_command_streak
    if last_keystrokes_hash is not None:
        updates["last_keystrokes_hash"] = last_keystrokes_hash
    if last_observation_hash is not None:
        updates["last_observation_hash"] = last_observation_hash
    if nudges_sent is not None:
        updates["nudges_sent"] = nudges_sent
    if forced_interrupts is not None:
        updates["forced_interrupts"] = forced_interrupts
    new_stall = replace(state.stall, **updates)
    return replace(state, stall=new_stall)


def with_stall(state: State, new_stall: StallState) -> State:
    """Replace the entire StallState (used when rewriting counters wholesale)."""
    return replace(state, stall=new_stall)
