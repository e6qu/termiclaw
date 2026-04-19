"""Events: the shell's report of what happened when it applied a command.

Events feed back into `decide.decide` which produces the next batch of
commands. Most commands produce exactly one event; `LoopTick` is a
shell-synthesized event that fires at the top of each iteration when
nothing else is in flight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from termiclaw.errors import (
        ArtifactRefreshError,
        ContainerError,
        PlannerError,
        SummarizationError,
    )
    from termiclaw.models import ParseResult, PlannerUsage, StepRecord


@dataclass(frozen=True, slots=True)
class LoopTick:
    """Synthetic start-of-iteration event.

    Carries two signals the shell pre-computed so `decide` stays pure:
    whether the worker is ready for a fresh summarization job, and
    whether the tmux session is still alive. `decide` uses these to
    choose the next commands without reaching outside its arguments.
    """

    summarize_ready: bool
    session_alive: bool


@dataclass(frozen=True, slots=True)
class ObservationCaptured:
    """`ObserveCmd` completed. `next_buffer` replaces `state.previous_buffer`."""

    text: str
    next_buffer: str


@dataclass(frozen=True, slots=True)
class PlannerResponded:
    """`QueryPlannerCmd` produced a structured response."""

    parsed: ParseResult
    usage: PlannerUsage


@dataclass(frozen=True, slots=True)
class PlannerFailedEvent:
    """claude -p subprocess failed (timeout, non-zero exit, parse error)."""

    error: PlannerError


@dataclass(frozen=True, slots=True)
class CommandAcked:
    """A `SendKeysCmd` or `ForceInterruptCmd` completed.

    `blocked_ok` is False if the marker-wait timed out (the command may
    still be running).
    """

    blocked_ok: bool


@dataclass(frozen=True, slots=True)
class SendKeysFailed:
    """A keystroke send errored at the container layer."""

    error: ContainerError


@dataclass(frozen=True, slots=True)
class SummarizationDone:
    """Background worker finished a summarization job."""

    summary: str
    qa_context: str


@dataclass(frozen=True, slots=True)
class SummarizationFailedEvent:
    """Background worker raised; run should fail."""

    error: SummarizationError


@dataclass(frozen=True, slots=True)
class ArtifactsRefreshed:
    """`RefreshArtifactsCmd` completed."""

    trigger: str


@dataclass(frozen=True, slots=True)
class ArtifactsRefreshFailedEvent:
    """`RefreshArtifactsCmd` failed; run should fail."""

    error: ArtifactRefreshError


@dataclass(frozen=True, slots=True)
class StepLogged:
    """`LogStepCmd` completed. Carries the step so `decide` can bump counters."""

    step: StepRecord


@dataclass(frozen=True, slots=True)
class SessionDiedEvent:
    """The tmux session inside the container is no longer alive."""


type Event = (
    LoopTick
    | ObservationCaptured
    | PlannerResponded
    | PlannerFailedEvent
    | CommandAcked
    | SendKeysFailed
    | SummarizationDone
    | SummarizationFailedEvent
    | ArtifactsRefreshed
    | ArtifactsRefreshFailedEvent
    | StepLogged
    | SessionDiedEvent
)
