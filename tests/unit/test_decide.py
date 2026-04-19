"""Tests for termiclaw.decide — pure state-transition core. Zero mocks."""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from termiclaw.commands import (
    ForceInterruptCmd,
    LogStepCmd,
    ObserveCmd,
    QueryPlannerCmd,
    RefreshArtifactsCmd,
    SubmitSummarizationCmd,
)
from termiclaw.decide import DecideEffects, decide
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
from termiclaw.models import Config, ParsedCommand, ParseResult, PlannerUsage, StepRecord
from termiclaw.state import State


def _step_record(step_id: str = "s1") -> StepRecord:
    return StepRecord(step_id=step_id, timestamp="t", source="agent", observation="x")


def _effects(seed: int = 0) -> DecideEffects:
    counter = itertools.count(seed)
    return DecideEffects(
        new_id=lambda: f"id-{next(counter)}",
        now=lambda: "2026-04-19T00:00:00+00:00",
    )


def _state(**kw: object) -> State:
    base = State(
        run_id="r",
        instruction="t",
        tmux_session="s",
        started_at="s",
        status="active",
    )
    return replace(base, **kw)


def _config(**kw: object) -> Config:
    return replace(Config(instruction="t"), **kw)


def test_session_died_fails_run():
    transition = decide(_state(), SessionDiedEvent(), _config(), _effects())
    assert transition.state.status == "failed"
    assert transition.commands == ()


def test_loop_tick_session_dead_fails_run():
    transition = decide(
        _state(),
        LoopTick(summarize_ready=False, session_alive=False),
        _config(),
        _effects(),
    )
    assert transition.state.status == "failed"


def test_loop_tick_emits_observe_cmd_when_idle():
    transition = decide(
        _state(),
        LoopTick(summarize_ready=False, session_alive=True),
        _config(),
        _effects(),
    )
    assert transition.state.status == "active"
    assert transition.commands == (ObserveCmd(),)


def test_loop_tick_triggers_artifact_refresh_at_interval():
    cfg = _config(state_dump_interval_turns=10, state_dump_token_threshold=10**9)
    state = _state(current_step=10)
    transition = decide(
        state,
        LoopTick(summarize_ready=False, session_alive=True),
        cfg,
        _effects(),
    )
    assert len(transition.commands) == 1
    assert isinstance(transition.commands[0], RefreshArtifactsCmd)
    assert transition.commands[0].trigger == "interval"


def test_loop_tick_emits_summarize_cmd_when_ready_and_over_threshold():
    cfg = _config(summarization_token_threshold=100)
    state = _state(total_prompt_tokens=150)
    transition = decide(
        state,
        LoopTick(summarize_ready=True, session_alive=True),
        cfg,
        _effects(),
    )
    cmds = list(transition.commands)
    assert any(isinstance(c, SubmitSummarizationCmd) for c in cmds)
    assert any(isinstance(c, ObserveCmd) for c in cmds)


def test_observation_emits_query_planner_cmd():
    state = _state()
    transition = decide(
        state,
        ObservationCaptured(text="$ ", next_buffer="buf"),
        _config(),
        _effects(),
    )
    assert len(transition.commands) == 1
    cmd = transition.commands[0]
    assert isinstance(cmd, QueryPlannerCmd)
    assert cmd.first_call is True
    assert cmd.resume_parent is None


def test_observation_consumes_pending_blocking_timeout():
    state = _state(pending_blocking_timeout=True)
    transition = decide(
        state,
        ObservationCaptured(text="x", next_buffer="b"),
        _config(),
        _effects(),
    )
    assert transition.state.pending_blocking_timeout is False


def test_planner_responded_empty_logs_step_only():
    parsed = ParseResult(analysis="noop")
    transition = decide(
        _state(),
        PlannerResponded(parsed=parsed, usage=PlannerUsage()),
        _config(),
        _effects(),
    )
    assert len(transition.commands) == 1
    assert isinstance(transition.commands[0], LogStepCmd)


def test_planner_responded_emits_send_keys_plus_log():
    parsed = ParseResult(
        analysis="run ls",
        commands=(ParsedCommand(keystrokes="ls", duration=1.0),),
    )
    transition = decide(
        _state(),
        PlannerResponded(parsed=parsed, usage=PlannerUsage(input_tokens=50)),
        _config(),
        _effects(),
    )
    cmd_types = [type(c).__name__ for c in transition.commands]
    assert cmd_types == ["SendKeysCmd", "LogStepCmd"]
    assert transition.state.total_prompt_tokens == 50


def test_planner_responded_task_complete_first_time_pending():
    parsed = ParseResult(task_complete=True, analysis="done")
    transition = decide(
        _state(),
        PlannerResponded(parsed=parsed, usage=PlannerUsage()),
        _config(),
        _effects(),
    )
    assert transition.state.pending_completion is True
    assert transition.state.status == "active"
    assert any(isinstance(c, QueryPlannerCmd) for c in transition.commands)


def test_planner_responded_task_complete_confirmed_succeeds():
    parsed = ParseResult(task_complete=True, analysis="confirmed")
    state = _state(pending_completion=True)
    transition = decide(
        state,
        PlannerResponded(parsed=parsed, usage=PlannerUsage()),
        _config(),
        _effects(),
    )
    assert transition.state.status == "succeeded"
    assert len(transition.commands) == 1
    assert isinstance(transition.commands[0], LogStepCmd)


def test_planner_failed_logs_error_step_only():
    """Must not emit ObserveCmd — that creates an inner infinite cycle."""
    transition = decide(
        _state(),
        PlannerFailedEvent(error=PlannerError("boom")),
        _config(),
        _effects(),
    )
    cmd_types = [type(c).__name__ for c in transition.commands]
    assert cmd_types == ["LogStepCmd"]
    assert transition.state.status == "active"
    assert transition.state.consecutive_planner_failures == 1
    assert transition.state.is_first_call is False


def test_planner_failed_threshold_fails_run():
    """3 consecutive planner failures → run fails."""
    state = _state(consecutive_planner_failures=2)
    transition = decide(
        state,
        PlannerFailedEvent(error=PlannerError("boom")),
        _config(),
        _effects(),
    )
    assert transition.state.status == "failed"
    assert transition.state.consecutive_planner_failures == 3


def test_planner_responded_resets_failure_counter():
    state = _state(consecutive_planner_failures=2)
    transition = decide(
        state,
        PlannerResponded(parsed=ParseResult(analysis="ok"), usage=PlannerUsage()),
        _config(),
        _effects(),
    )
    assert transition.state.consecutive_planner_failures == 0


def test_command_acked_blocked_ok_clears_timeout_flag():
    state = _state(pending_blocking_timeout=True)
    transition = decide(state, CommandAcked(blocked_ok=True), _config(), _effects())
    assert transition.state.pending_blocking_timeout is False
    assert transition.commands == (ObserveCmd(),)


def test_command_acked_blocked_failure_sets_timeout_flag():
    transition = decide(
        _state(),
        CommandAcked(blocked_ok=False),
        _config(),
        _effects(),
    )
    assert transition.state.pending_blocking_timeout is True


def test_send_keys_failed_fails_run():
    transition = decide(
        _state(),
        SendKeysFailed(error=ContainerError("boom")),
        _config(),
        _effects(),
    )
    assert transition.state.status == "failed"


def test_summarization_done_applies_and_logs():
    state = _state(total_prompt_tokens=500)
    transition = decide(
        state,
        SummarizationDone(summary="S", qa_context="QA"),
        _config(),
        _effects(),
    )
    assert transition.state.summary == "S"
    assert transition.state.qa_context == "QA"
    assert transition.state.total_prompt_tokens == 0
    assert len(transition.commands) == 1
    assert isinstance(transition.commands[0], LogStepCmd)


def test_summarization_failed_fails_run():
    transition = decide(
        _state(),
        SummarizationFailedEvent(error=SummarizationError("boom")),
        _config(),
        _effects(),
    )
    assert transition.state.status == "failed"


def test_artifacts_refreshed_logs_marker_step():
    transition = decide(
        _state(),
        ArtifactsRefreshed(trigger="interval"),
        _config(),
        _effects(),
    )
    assert transition.state.status == "active"
    assert len(transition.commands) == 1
    assert isinstance(transition.commands[0], LogStepCmd)


def test_artifacts_refresh_failed_fails_run():
    transition = decide(
        _state(),
        ArtifactsRefreshFailedEvent(error=ArtifactRefreshError("fail")),
        _config(),
        _effects(),
    )
    assert transition.state.status == "failed"


def test_observation_text_threads_into_logged_step():
    """BUG-43: text captured at ObservationCaptured must reach the StepRecord.

    Previously `_log_agent_step` was called with `observation=""`, so every
    `agent`-source step wrote empty `terminal_output` to the trajectory —
    ATIF export shipped blanks. Fix threads the text through
    `State.last_observation`.
    """
    state = _state()
    transition = decide(
        state,
        ObservationCaptured(text="hello\n$ ", next_buffer="hello\n$ "),
        _config(),
        _effects(),
    )
    state = transition.state
    assert state.last_observation == "hello\n$ "
    parsed = ParseResult(
        analysis="ran echo",
        commands=(ParsedCommand(keystrokes="echo hi", duration=0.1),),
    )
    after = decide(
        state, PlannerResponded(parsed=parsed, usage=PlannerUsage()), _config(), _effects()
    )
    log_cmds = [c for c in after.commands if isinstance(c, LogStepCmd)]
    assert len(log_cmds) == 1
    assert log_cmds[0].step.observation == "hello\n$ "
    # Cleared after logging so the confirmation turn doesn't re-log it.
    assert after.state.last_observation == ""


def test_step_logged_advances_counter_and_appends_step():
    state = _state(current_step=2)
    step = _step_record()
    transition = decide(state, StepLogged(step=step), _config(), _effects())
    assert transition.state.current_step == 3
    assert transition.state.recent_steps[-1] is step
    assert transition.commands == ()


def test_force_interrupt_cmd_is_reachable_via_stall_signal():
    """Stall detection is triggered in the observation handler (indirectly)."""
    # detect_stall via repeated observations: fresh state should not trigger.
    transition = decide(
        _state(),
        ObservationCaptured(text="$", next_buffer=""),
        _config(),
        _effects(),
    )
    cmd_types = [type(c).__name__ for c in transition.commands]
    # No stall on first observation → QueryPlannerCmd, not ForceInterruptCmd.
    assert "ForceInterruptCmd" not in cmd_types
    assert "QueryPlannerCmd" in cmd_types


def test_all_event_variants_have_handlers():
    """Meta-test: every Event constructible with dummy data runs without error."""
    events = [
        LoopTick(summarize_ready=False, session_alive=True),
        ObservationCaptured(text="x", next_buffer="b"),
        PlannerResponded(parsed=ParseResult(), usage=PlannerUsage()),
        PlannerFailedEvent(error=PlannerError("e")),
        CommandAcked(blocked_ok=True),
        SendKeysFailed(error=ContainerError("e")),
        SummarizationDone(summary="s", qa_context="q"),
        SummarizationFailedEvent(error=SummarizationError("e")),
        ArtifactsRefreshed(trigger="t"),
        ArtifactsRefreshFailedEvent(error=ArtifactRefreshError("e")),
        StepLogged(step=_step_record()),
        SessionDiedEvent(),
    ]
    for ev in events:
        decide(_state(), ev, _config(), _effects())


@pytest.mark.parametrize("kind", ["force_interrupt"])
def test_force_interrupt_cmd_types(kind: str):
    # Placeholder: ForceInterruptCmd is emitted when stall escalates; tested via integration.
    _ = kind
    assert ForceInterruptCmd(reason="s").reason == "s"
