"""Tests for termiclaw.shell.apply — uses `tests/unit/fakes` for DI."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
    PlannerSubprocessError,
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
from termiclaw.models import Config, ParseResult, PlannerUsage, StepRecord
from termiclaw.result import Err, Ok
from termiclaw.shell import apply
from termiclaw.state import State
from termiclaw.summarize_worker import SummarizationJob
from tests.unit.fakes import (
    FakeArtifactsPort,
    FakeContainerPort,
    FakePersistencePort,
    FakePlannerPort,
    FakeSummarizePort,
    build_fake_ports,
)


def _state(**kw: object) -> State:
    base = State(
        run_id="r",
        instruction="t",
        tmux_session="s",
        started_at="s",
        status="active",
        container_id="c",
        claude_session_id="sess",
    )
    return replace(base, **kw)


def _config() -> Config:
    return Config(instruction="t")


def test_apply_observe_captures_text_and_buffer():
    container = FakeContainerPort()
    container.incremental_outputs.append(("$ hello\n", "buffer-xyz"))
    ports = build_fake_ports(container=container)
    event = apply(
        ObserveCmd(),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, ObservationCaptured)
    assert event.text == "$ hello\n"
    assert event.next_buffer == "buffer-xyz"


def test_apply_send_keys_returns_command_acked():
    container = FakeContainerPort(send_and_wait_result=True)
    ports = build_fake_ports(container=container)
    event = apply(
        SendKeysCmd(keystrokes="ls", max_seconds=5.0),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, CommandAcked)
    assert event.blocked_ok is True
    assert container.sent_keys == [("ls", 16_000)]


def test_apply_send_keys_container_error_returns_fail_event():
    container = FakeContainerPort(send_and_wait_raises=ContainerError("fail"))
    ports = build_fake_ports(container=container)
    event = apply(
        SendKeysCmd(keystrokes="ls", max_seconds=5.0),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, SendKeysFailed)


def test_apply_force_interrupt_sends_ctrl_c():
    container = FakeContainerPort()
    ports = build_fake_ports(container=container)
    event = apply(
        ForceInterruptCmd(reason="stall"),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, CommandAcked)
    assert container.interrupts == ["C-c"]


def test_apply_force_interrupt_error_returns_fail_event():
    container = FakeContainerPort(send_keys_raises=ContainerError("fail"))
    ports = build_fake_ports(container=container)
    event = apply(
        ForceInterruptCmd(reason="stall"),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, SendKeysFailed)


def test_apply_query_planner_parses_response():
    planner = FakePlannerPort()
    planner.query_responses.append(Ok('{"result":"ok"}'))
    planner.parse_responses.append(Ok(ParseResult(analysis="a")))
    planner.usage_responses.append(PlannerUsage(input_tokens=42))
    ports = build_fake_ports(planner=planner)
    event = apply(
        QueryPlannerCmd(prompt="hi", first_call=True, resume_parent=None, fork_session=False),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, PlannerResponded)
    assert event.usage.input_tokens == 42
    assert event.parsed.analysis == "a"


def test_apply_query_planner_subprocess_error_returns_failed():
    planner = FakePlannerPort()
    err: Err[PlannerError] = Err(PlannerSubprocessError(1, "boom"))
    planner.query_responses.append(err)
    ports = build_fake_ports(planner=planner)
    event = apply(
        QueryPlannerCmd(prompt="hi", first_call=True, resume_parent=None, fork_session=False),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, PlannerFailedEvent)


def test_apply_query_planner_parse_error_wraps_as_planner_failed():
    planner = FakePlannerPort()
    planner.query_responses.append(Ok('{"bad"}'))
    planner.parse_responses.append(Err(PlannerError("invalid")))
    ports = build_fake_ports(planner=planner)
    event = apply(
        QueryPlannerCmd(prompt="hi", first_call=True, resume_parent=None, fork_session=False),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, PlannerFailedEvent)


def test_apply_submit_summarization_queues_job():
    worker = FakeSummarizePort()
    ports = build_fake_ports(summarize=worker)
    job = SummarizationJob(
        instruction="t",
        recent_text="r",
        full_text="f",
        visible_screen="v",
    )
    event = apply(
        SubmitSummarizationCmd(job=job),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, LoopTick)
    assert worker.submitted == [job]


def test_apply_refresh_artifacts_success():
    artifacts = FakeArtifactsPort()
    ports = build_fake_ports(artifacts=artifacts)
    event = apply(
        RefreshArtifactsCmd(trigger="interval"),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, ArtifactsRefreshed)
    assert event.trigger == "interval"
    assert len(artifacts.calls) == 1


def test_apply_refresh_artifacts_failure_returns_fail_event():
    artifacts = FakeArtifactsPort(refresh_raises=ArtifactRefreshError("fail"))
    ports = build_fake_ports(artifacts=artifacts)
    event = apply(
        RefreshArtifactsCmd(trigger="interval"),
        ports,
        state=_state(),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, ArtifactsRefreshFailedEvent)


def test_apply_log_step_persists_to_trajectory_and_db():
    persistence = FakePersistencePort()
    ports = build_fake_ports(persistence=persistence)
    step = StepRecord(
        step_id="s1",
        timestamp="t",
        source="agent",
        observation="out",
    )
    event = apply(
        LogStepCmd(step=step, usage=PlannerUsage(input_tokens=10, output_tokens=5)),
        ports,
        state=_state(current_step=7),
        run_dir=Path("/run"),
        config=_config(),
    )
    assert isinstance(event, StepLogged)
    assert len(persistence.appended) == 1
    assert persistence.appended[0][1] is step
    assert len(persistence.inserted_steps) == 1
    assert persistence.inserted_steps[0].step_index == 7
    assert persistence.inserted_steps[0].input_tokens == 10
