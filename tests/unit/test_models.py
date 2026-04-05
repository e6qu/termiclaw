"""Tests for termiclaw.models."""

import dataclasses

from termiclaw.models import Config, ParsedCommand, ParseResult, RunState, StepRecord


def test_parsed_command_frozen():
    cmd = ParsedCommand(keystrokes="ls\n", duration=0.5)
    assert cmd.keystrokes == "ls\n"
    assert cmd.duration == 0.5
    assert dataclasses.is_dataclass(cmd)
    assert ParsedCommand.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_parse_result_defaults():
    result = ParseResult()
    assert result.analysis == ""
    assert result.plan == ""
    assert result.commands == ()
    assert result.task_complete is False
    assert result.error is None
    assert result.warning is None


def test_parse_result_with_error():
    result = ParseResult(error="bad json")
    assert result.error == "bad json"
    assert result.commands == ()


def test_parse_result_with_commands():
    cmd = ParsedCommand(keystrokes="echo hi\n", duration=0.1)
    result = ParseResult(commands=(cmd,))
    assert len(result.commands) == 1
    assert result.commands[0].keystrokes == "echo hi\n"


def test_run_state_mutable():
    state = RunState(
        run_id="abc",
        instruction="do stuff",
        tmux_session="termiclaw-abc",
        started_at="2026-04-05T00:00:00Z",
        status="pending",
    )
    assert state.current_step == 0
    state.current_step = 5
    assert state.current_step == 5
    state.status = "active"
    assert state.status == "active"
    state.pending_completion = True
    assert state.pending_completion is True


def test_run_state_defaults():
    state = RunState(
        run_id="abc",
        instruction="x",
        tmux_session="t",
        started_at="t",
        status="pending",
    )
    assert state.max_turns == 1_000_000
    assert state.previous_buffer == ""
    assert state.summary is None
    assert state.qa_context is None
    assert state.total_prompt_chars == 0


def test_step_record_frozen():
    step = StepRecord(
        step_id="s1",
        timestamp="2026-04-05T00:00:00Z",
        source="agent",
        observation="terminal output",
    )
    assert step.step_id == "s1"
    assert step.commands == ()
    assert step.metrics == ()
    assert step.is_copied_context is False
    assert StepRecord.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_step_record_with_data():
    cmd = ParsedCommand(keystrokes="ls\n", duration=0.5)
    step = StepRecord(
        step_id="s1",
        timestamp="t",
        source="agent",
        observation="out",
        analysis="looks good",
        plan="run ls",
        commands=(cmd,),
        task_complete=True,
        metrics=(("prompt_chars", 1500), ("duration_ms", 3200)),
    )
    assert step.analysis == "looks good"
    assert step.task_complete is True
    assert len(step.metrics) == 2


def test_config_defaults():
    cfg = Config(instruction="fix bug")
    assert cfg.instruction == "fix bug"
    assert cfg.max_turns == 1_000_000
    assert cfg.pane_width == 160
    assert cfg.pane_height == 40
    assert cfg.history_limit == 10_000_000
    assert cfg.max_output_bytes == 10_000
    assert cfg.max_command_length == 16_000
    assert cfg.max_duration == 60.0
    assert cfg.min_delay == 0.1
    assert cfg.planner_timeout == 300
    assert cfg.planner_retries == 3
    assert cfg.summarization_threshold == 100_000
    assert cfg.keep_session is False
    assert cfg.runs_dir == "./termiclaw_runs"


def test_config_custom():
    cfg = Config(
        instruction="deploy",
        max_turns=50,
        keep_session=True,
        runs_dir="./test_runs",
    )
    assert cfg.max_turns == 50
    assert cfg.keep_session is True
    assert cfg.runs_dir == "./test_runs"


def test_config_verbose_default():
    cfg = Config(instruction="fix bug")
    assert cfg.verbose is False


def test_config_verbose_true():
    cfg = Config(instruction="fix bug", verbose=True)
    assert cfg.verbose is True


def test_run_state_recent_steps_default():
    state = RunState(
        run_id="abc",
        instruction="x",
        tmux_session="t",
        started_at="t",
        status="pending",
    )
    assert state.recent_steps == []


def test_config_frozen():
    assert Config.__dataclass_params__.frozen  # type: ignore[attr-defined]
