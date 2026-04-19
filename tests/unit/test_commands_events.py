"""Tests for termiclaw.commands and termiclaw.events."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
    SummarizationError,
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
from termiclaw.models import ParsedCommand, ParseResult, PlannerUsage, StepRecord
from termiclaw.summarize_worker import SummarizationJob

if TYPE_CHECKING:
    from termiclaw.commands import Command
    from termiclaw.events import Event


def _step() -> StepRecord:
    return StepRecord(step_id="s", timestamp="t", source="agent", observation="x")


def _usage() -> PlannerUsage:
    return PlannerUsage()


def _all_commands() -> list[Command]:
    return [
        ObserveCmd(),
        SendKeysCmd(keystrokes="ls", max_seconds=5.0),
        ForceInterruptCmd(reason="stall"),
        QueryPlannerCmd(prompt="hi", first_call=True, resume_parent=None, fork_session=False),
        SubmitSummarizationCmd(
            job=SummarizationJob(
                instruction="t", recent_text="r", full_text="f", visible_screen="v"
            ),
        ),
        RefreshArtifactsCmd(trigger="interval"),
        LogStepCmd(step=_step(), usage=_usage()),
    ]


def _all_events() -> list[Event]:
    parsed = ParseResult(
        analysis="a",
        plan="p",
        commands=(ParsedCommand(keystrokes="ls", duration=1.0),),
    )
    return [
        LoopTick(summarize_ready=False, session_alive=True),
        ObservationCaptured(text="x", next_buffer="b"),
        PlannerResponded(parsed=parsed, usage=_usage()),
        PlannerFailedEvent(error=PlannerError("boom")),
        CommandAcked(blocked_ok=True),
        SendKeysFailed(error=ContainerError("fail")),
        SummarizationDone(summary="s", qa_context="qa"),
        SummarizationFailedEvent(error=SummarizationError("boom")),
        ArtifactsRefreshed(trigger="interval"),
        ArtifactsRefreshFailedEvent(error=ArtifactRefreshError("fail")),
        StepLogged(step=_step()),
        SessionDiedEvent(),
    ]


def test_commands_are_frozen():
    cmd = SendKeysCmd(keystrokes="ls", max_seconds=5.0)
    with pytest.raises(AttributeError):
        setattr(cmd, "keystrokes", "rm")  # noqa: B010


def test_events_are_frozen():
    event = CommandAcked(blocked_ok=True)
    with pytest.raises(AttributeError):
        setattr(event, "blocked_ok", False)  # noqa: B010


def test_commands_are_hashable():
    for cmd in _all_commands():
        hash(cmd)


def test_events_are_hashable():
    for event in _all_events():
        hash(event)


def test_command_equality():
    a = SendKeysCmd(keystrokes="ls", max_seconds=5.0)
    b = SendKeysCmd(keystrokes="ls", max_seconds=5.0)
    assert a == b


def _describe_command(cmd: Command) -> str:  # noqa: PLR0911 — one return per variant
    """Exhaustive match on Command — CI enforces this branches every variant."""
    match cmd:
        case ObserveCmd():
            return "observe"
        case SendKeysCmd():
            return "send_keys"
        case ForceInterruptCmd():
            return "force_interrupt"
        case QueryPlannerCmd():
            return "query_planner"
        case SubmitSummarizationCmd():
            return "submit_summarization"
        case RefreshArtifactsCmd():
            return "refresh_artifacts"
        case LogStepCmd():
            return "log_step"


def _describe_event(event: Event) -> str:  # noqa: C901, PLR0911 — one return per variant
    """Exhaustive match on Event — CI enforces this branches every variant."""
    match event:
        case LoopTick():
            return "loop_tick"
        case ObservationCaptured():
            return "observation_captured"
        case PlannerResponded():
            return "planner_responded"
        case PlannerFailedEvent():
            return "planner_failed"
        case CommandAcked():
            return "command_acked"
        case SendKeysFailed():
            return "send_keys_failed"
        case SummarizationDone():
            return "summarization_done"
        case SummarizationFailedEvent():
            return "summarization_failed"
        case ArtifactsRefreshed():
            return "artifacts_refreshed"
        case ArtifactsRefreshFailedEvent():
            return "artifacts_refresh_failed"
        case StepLogged():
            return "step_logged"
        case SessionDiedEvent():
            return "session_died"


def test_command_union_exhaustive():
    """Every Command variant is pattern-matchable in a match over `Command`."""
    descriptions = {_describe_command(c) for c in _all_commands()}
    assert len(descriptions) == len(_all_commands())


def test_event_union_exhaustive():
    """Every Event variant is pattern-matchable in a match over `Event`."""
    descriptions = {_describe_event(e) for e in _all_events()}
    assert len(descriptions) == len(_all_events())
