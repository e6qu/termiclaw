"""Tests for termiclaw.agent."""

import json
import subprocess as sp
from unittest.mock import patch

from termiclaw.agent import (
    _execute_commands,
    _handle_completion,
    _handle_parse_error,
    _log_step,
    _termination_reason,
    run,
)
from termiclaw.models import Config, ParsedCommand, ParseResult, RunState


def _make_state(
    run_id: str = "abc123",
    instruction: str = "fix bug",
    tmux_session: str = "termiclaw-abc",
    started_at: str = "2026-04-05T00:00:00Z",
    status: str = "active",
    **kwargs,
) -> RunState:
    return RunState(
        run_id=run_id,
        instruction=instruction,
        tmux_session=tmux_session,
        started_at=started_at,
        status=status,
        **kwargs,
    )


# --- Termination reason ---


def test_termination_reason_succeeded():
    state = _make_state(status="succeeded")
    assert _termination_reason(state) == "task_complete_confirmed"


def test_termination_reason_cancelled():
    state = _make_state(status="cancelled")
    assert _termination_reason(state) == "keyboard_interrupt"


def test_termination_reason_failed():
    state = _make_state(status="failed")
    assert _termination_reason(state) == "max_turns_or_failure"


# --- Parse error handling ---


def test_handle_parse_error(tmp_path):
    state = _make_state()
    parsed = ParseResult(error="bad json")
    _handle_parse_error(state, parsed, tmp_path, "observation")
    assert state.current_step == 1
    trajectory_file = tmp_path / "trajectory.jsonl"
    assert trajectory_file.exists()
    data = json.loads(trajectory_file.read_text().strip())
    assert data["error"] == "bad json"


# --- Completion handling ---


def test_handle_completion_first_time(tmp_path):
    state = _make_state()
    parsed = ParseResult(task_complete=True, analysis="done")
    result = _handle_completion(state, parsed, tmp_path, "obs")
    assert result is False
    assert state.pending_completion is True


def test_handle_completion_confirmed(tmp_path):
    state = _make_state(pending_completion=True)
    parsed = ParseResult(task_complete=True, analysis="confirmed done")
    result = _handle_completion(state, parsed, tmp_path, "obs")
    assert result is True
    assert state.status == "succeeded"
    assert state.current_step == 1


# --- Command execution ---


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.time")
def test_execute_commands(mock_time, mock_tmux):
    state = _make_state()
    config = Config(instruction="fix bug", max_duration=60.0, min_delay=0.1)
    cmd = ParsedCommand(keystrokes="ls\n", duration=0.5)
    parsed = ParseResult(commands=(cmd,))
    _execute_commands(state, config, parsed)
    mock_tmux.send_keys.assert_called_once_with("termiclaw-abc", "ls\n")
    assert mock_time.sleep.call_count == 2


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.time")
def test_execute_commands_duration_capped(mock_time, mock_tmux):
    state = _make_state()
    config = Config(instruction="fix bug", max_duration=5.0, min_delay=0.1)
    cmd = ParsedCommand(keystrokes="make\n", duration=120.0)
    parsed = ParseResult(commands=(cmd,))
    _execute_commands(state, config, parsed)
    mock_time.sleep.assert_any_call(5.0)


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.time")
def test_execute_commands_empty(mock_time, mock_tmux):
    state = _make_state()
    config = Config(instruction="fix bug", max_duration=60.0, min_delay=0.1)
    parsed = ParseResult(commands=())
    _execute_commands(state, config, parsed)
    mock_tmux.send_keys.assert_not_called()
    mock_time.sleep.assert_not_called()


# --- Step logging + recent_steps ---


def test_log_step(tmp_path):
    state = _make_state()
    parsed = ParseResult(
        analysis="checked files",
        plan="run tests",
        commands=(ParsedCommand(keystrokes="ls\n", duration=0.5),),
    )
    _log_step(state, "terminal output", parsed, tmp_path)
    assert state.current_step == 1
    data = json.loads((tmp_path / "trajectory.jsonl").read_text().strip())
    assert data["message"] == "checked files"
    assert data["observation"]["terminal_output"] == "terminal output"
    assert len(state.recent_steps) == 1
    assert state.recent_steps[0].analysis == "checked files"


def test_handle_parse_error_populates_recent_steps(tmp_path):
    state = _make_state()
    parsed = ParseResult(error="bad json")
    _handle_parse_error(state, parsed, tmp_path, "observation")
    assert len(state.recent_steps) == 1
    assert state.recent_steps[0].error == "bad json"


def test_handle_completion_populates_recent_steps(tmp_path):
    state = _make_state(pending_completion=True)
    parsed = ParseResult(task_complete=True, analysis="confirmed done")
    _handle_completion(state, parsed, tmp_path, "obs")
    assert len(state.recent_steps) == 1


# --- Planner failure logging ---


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.planner")
@patch("termiclaw.agent.time")
def test_run_planner_failure_logged(mock_time, mock_planner, mock_tmux, tmp_path):
    mock_tmux.is_session_alive.side_effect = [True, False]
    mock_planner.build_prompt.return_value = "prompt"
    mock_planner.query_planner.side_effect = RuntimeError("fail")

    config = Config(instruction="task", max_turns=2, runs_dir=str(tmp_path / "runs"))
    state = run(config)
    # The planner failure should be logged as a step
    assert state.current_step >= 1
    assert len(state.recent_steps) >= 1
    assert state.recent_steps[0].error == "Planner failed after retries"


# --- Provision failure ---


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.time")
def test_run_provision_failure(mock_time, mock_tmux, tmp_path):
    mock_tmux.provision_session.side_effect = sp.CalledProcessError(1, "tmux")

    config = Config(instruction="task", runs_dir=str(tmp_path / "runs"))
    state = run(config)
    assert state.status == "failed"


# --- Full run (heavily mocked) ---


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.planner")
@patch("termiclaw.agent.time")
def test_run_simple_task(mock_time, mock_planner, mock_tmux, tmp_path):
    mock_tmux.is_session_alive.side_effect = [True, True, True]
    mock_tmux.get_incremental_output.return_value = (
        "New Terminal Output:\nhello",
        "buffer",
    )
    mock_tmux.truncate_output.side_effect = lambda text, **_kw: text
    mock_tmux.capture_visible.return_value = "screen"

    mock_planner.build_prompt.return_value = "prompt"
    mock_planner.query_planner.return_value = '{"result":"ok"}'
    mock_planner.parse_response.side_effect = [
        ParseResult(
            analysis="a",
            plan="p",
            commands=(ParsedCommand(keystrokes="echo hi\n", duration=0.1),),
        ),
        ParseResult(task_complete=True, analysis="done"),
        ParseResult(task_complete=True, analysis="confirmed"),
    ]

    config = Config(instruction="say hi", runs_dir=str(tmp_path / "runs"))
    state = run(config)
    assert state.status == "succeeded"
    assert state.current_step >= 1


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.planner")
@patch("termiclaw.agent.time")
def test_run_session_dies(mock_time, mock_planner, mock_tmux, tmp_path):
    mock_tmux.is_session_alive.return_value = False

    config = Config(instruction="task", runs_dir=str(tmp_path / "runs"))
    state = run(config)
    assert state.status == "failed"


@patch("termiclaw.agent.tmux")
@patch("termiclaw.agent.planner")
@patch("termiclaw.agent.time")
def test_run_max_turns(mock_time, mock_planner, mock_tmux, tmp_path):
    mock_tmux.is_session_alive.return_value = True
    mock_tmux.get_incremental_output.return_value = ("output", "buf")
    mock_tmux.truncate_output.side_effect = lambda text, **_kw: text

    mock_planner.build_prompt.return_value = "p"
    mock_planner.query_planner.return_value = '{"result":"ok"}'
    mock_planner.parse_response.return_value = ParseResult(
        analysis="a",
        commands=(ParsedCommand(keystrokes="x\n", duration=0.1),),
    )

    config = Config(instruction="task", max_turns=3, runs_dir=str(tmp_path / "runs"))
    state = run(config)
    assert state.status == "failed"
    assert state.current_step == 3
