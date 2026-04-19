"""Commands: descriptions of side effects the functional core wants done.

A `Command` is a frozen dataclass; it does nothing until the imperative
shell (`shell.apply`) pattern-matches on it. The functional core
(`decide.decide`) emits commands in response to events but never invokes
I/O directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from termiclaw.models import PlannerUsage, StepRecord
    from termiclaw.summarize_worker import SummarizationJob


@dataclass(frozen=True, slots=True)
class ObserveCmd:
    """Capture + diff the terminal; produces `ObservationCaptured`."""


@dataclass(frozen=True, slots=True)
class SendKeysCmd:
    """Send keystrokes via `container.send_and_wait_idle`."""

    keystrokes: str
    max_seconds: float


@dataclass(frozen=True, slots=True)
class ForceInterruptCmd:
    """Send C-c to the container's tmux session."""

    reason: str


@dataclass(frozen=True, slots=True)
class QueryPlannerCmd:
    """Invoke claude -p; produces `PlannerResponded` or `PlannerFailedEvent`."""

    prompt: str
    first_call: bool
    resume_parent: str | None
    fork_session: bool


@dataclass(frozen=True, slots=True)
class SubmitSummarizationCmd:
    """Hand a pre-built job to the background summarization worker.

    Fire-and-forget: result appears in a later `LoopTick` when the worker
    finishes, via `SummarizationDone` / `SummarizationFailedEvent`.
    """

    job: SummarizationJob


@dataclass(frozen=True, slots=True)
class RefreshArtifactsCmd:
    """Regenerate the four state-dump markdown files."""

    trigger: str


@dataclass(frozen=True, slots=True)
class LogStepCmd:
    """Persist a StepRecord to trajectory JSONL + SQLite."""

    step: StepRecord
    usage: PlannerUsage


type Command = (
    ObserveCmd
    | SendKeysCmd
    | ForceInterruptCmd
    | QueryPlannerCmd
    | SubmitSummarizationCmd
    | RefreshArtifactsCmd
    | LogStepCmd
)
