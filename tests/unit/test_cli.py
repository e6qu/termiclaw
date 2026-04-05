"""Tests for termiclaw.cli."""

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from termiclaw.cli import (
    _attach,
    _check_claude,
    _check_tmux,
    _finish_update_check,
    _get_local_version,
    _list_runs,
    _parse_latest_tag,
    _print_run_header,
    _print_trajectory,
    _resolve_run_dir,
    _run,
    _show,
    _start_update_check,
    _status,
    _version_tuple,
)
from termiclaw.models import RunInfo

# --- Startup checks ---


def test_check_tmux_present():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _check_tmux()


def test_check_tmux_missing():
    with (
        patch("termiclaw.cli.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(SystemExit),
    ):
        _check_tmux()


def test_check_claude_present():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _check_claude()


def test_check_claude_missing():
    with (
        patch("termiclaw.cli.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(SystemExit),
    ):
        _check_claude()


def test_check_tmux_command_fails():
    with (
        patch(
            "termiclaw.cli.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "tmux"),
        ),
        pytest.raises(SystemExit),
    ):
        _check_tmux()


def test_check_claude_command_fails():
    with (
        patch(
            "termiclaw.cli.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "claude"),
        ),
        pytest.raises(SystemExit),
    ):
        _check_claude()


# --- run ---


def test_run_task_file_not_found():
    args = argparse.Namespace(
        instruction=None,
        task="/nonexistent/path/task.txt",
        max_turns=10,
        keep_session=False,
        runs_dir="./runs",
        verbose=False,
    )
    with (
        patch("termiclaw.cli._check_tmux"),
        patch("termiclaw.cli._check_claude"),
        pytest.raises(SystemExit),
    ):
        _run(args)


def test_run_no_instruction():
    args = argparse.Namespace(
        instruction=None,
        task=None,
        max_turns=10,
        keep_session=False,
        runs_dir="./runs",
        verbose=False,
    )
    with (
        patch("termiclaw.cli._check_tmux"),
        patch("termiclaw.cli._check_claude"),
        pytest.raises(SystemExit),
    ):
        _run(args)


def test_run_with_instruction():
    args = argparse.Namespace(
        instruction="do stuff",
        task=None,
        max_turns=10,
        keep_session=False,
        runs_dir="./runs",
        verbose=False,
    )
    with (
        patch("termiclaw.cli._check_tmux"),
        patch("termiclaw.cli._check_claude"),
        patch("termiclaw.cli.agent") as mock_agent,
    ):
        mock_agent.run.return_value = MagicMock(
            run_id="abc",
            status="succeeded",
            current_step=1,
        )
        _run(args)
        mock_agent.run.assert_called_once()
        config = mock_agent.run.call_args[0][0]
        assert config.instruction == "do stuff"


# --- attach ---


def test_attach_session_not_found():
    args = argparse.Namespace(run_id="nonexistent123")
    with (
        patch("termiclaw.cli.tmux.is_session_alive", return_value=False),
        patch(
            "termiclaw.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="",
            ),
        ),
        pytest.raises(SystemExit),
    ):
        _attach(args)


def test_attach_exact_match():
    args = argparse.Namespace(run_id="abc12345")
    with (
        patch("termiclaw.cli.tmux.is_session_alive", return_value=True),
        patch("termiclaw.cli.tmux.attach_session") as mock_attach,
    ):
        _attach(args)
        mock_attach.assert_called_once_with("termiclaw-abc12345")


# --- list ---


def test_list_runs_empty(tmp_path):
    args = argparse.Namespace(runs_dir=str(tmp_path))
    _list_runs(args)  # should print "No runs found." to stderr


def test_list_runs_with_data(tmp_path):
    mock_runs = [
        RunInfo(
            run_id="abc12345",
            instruction="fix the bug",
            status="succeeded",
            total_steps=3,
            started_at="2026-04-05T00:00:00Z",
            finished_at="2026-04-05T00:01:00Z",
            tmux_session="t",
            termination_reason="done",
            prompt_chars=5000,
            duration="1m 0s",
        ),
    ]
    args = argparse.Namespace(runs_dir=str(tmp_path))
    with patch("termiclaw.cli.trajectory.list_runs", return_value=mock_runs):
        _list_runs(args)


def test_list_runs_truncates_instruction(tmp_path):
    long_instruction = "a" * 100
    mock_runs = [
        RunInfo(
            run_id="abc",
            instruction=long_instruction,
            status="succeeded",
            total_steps=1,
            started_at="t",
            finished_at="t",
            tmux_session="t",
            termination_reason="done",
            prompt_chars=0,
            duration="-",
        ),
    ]
    args = argparse.Namespace(runs_dir=str(tmp_path))
    with patch("termiclaw.cli.trajectory.list_runs", return_value=mock_runs):
        _list_runs(args)


# --- show ---


def test_resolve_run_dir_not_found(tmp_path):
    with pytest.raises(SystemExit):
        _resolve_run_dir(tmp_path, "nonexistent")


def test_resolve_run_dir_found(tmp_path):
    run_dir = tmp_path / "abc12345"
    run_dir.mkdir()
    result = _resolve_run_dir(tmp_path, "abc")
    assert result == run_dir


def test_resolve_run_dir_ambiguous(tmp_path):
    (tmp_path / "abc111").mkdir()
    (tmp_path / "abc222").mkdir()
    with pytest.raises(SystemExit):
        _resolve_run_dir(tmp_path, "abc")


def test_resolve_run_dir_nonexistent_parent():
    with pytest.raises(SystemExit):
        _resolve_run_dir(Path("/nonexistent"), "abc")


def test_print_run_header(tmp_path):
    meta = {
        "run_id": "abc",
        "status": "succeeded",
        "instruction": "fix bug",
        "total_steps": 3,
        "started_at": "2026-04-05T00:00:00Z",
        "finished_at": "2026-04-05T00:01:00Z",
    }
    (tmp_path / "run.json").write_text(json.dumps(meta))
    _print_run_header(tmp_path)


def test_print_run_header_no_file(tmp_path):
    _print_run_header(tmp_path)  # should not raise


def test_print_trajectory(tmp_path):
    steps = [
        {
            "step_id": "s1",
            "source": "agent",
            "message": "checking",
            "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": "ls\n"}}],
            "error": None,
        },
        {
            "step_id": "s2",
            "source": "error",
            "message": "",
            "tool_calls": [],
            "error": "parse failed",
        },
    ]
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text("\n".join(json.dumps(s) for s in steps) + "\n")
    _print_trajectory(tmp_path)


def test_print_trajectory_no_file(tmp_path):
    _print_trajectory(tmp_path)  # should print "No trajectory found."


def test_show(tmp_path):
    run_dir = tmp_path / "abc12345"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"run_id": "abc12345", "status": "succeeded"}))
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps({"step_id": "s1", "source": "agent", "message": "hi", "tool_calls": []}) + "\n",
    )
    args = argparse.Namespace(runs_dir=str(tmp_path), run_id="abc")
    _show(args)


# --- status ---


def test_status_success():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"status":"ok"}',
            stderr="",
        )
        _status()


def test_status_failure():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="rate limited",
        )
        _status()


def test_status_not_found():
    with (
        patch("termiclaw.cli.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(SystemExit),
    ):
        _status()


def test_status_timeout():
    with (
        patch(
            "termiclaw.cli.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=30),
        ),
        pytest.raises(SystemExit),
    ):
        _status()


# --- Version check ---


def test_version_tuple():
    assert _version_tuple("1.2.3") == (1, 2, 3)
    assert _version_tuple("0.4.0") == (0, 4, 0)
    assert _version_tuple("10.0.1") == (10, 0, 1)
    assert _version_tuple("bad") == (0,)


def test_parse_latest_tag():
    output = (
        "abc123\trefs/tags/termiclaw-v0.1.0\n"
        "def456\trefs/tags/termiclaw-v0.3.0\n"
        "ghi789\trefs/tags/termiclaw-v0.2.0\n"
    )
    assert _parse_latest_tag(output) == "0.3.0"


def test_parse_latest_tag_empty():
    assert _parse_latest_tag("") == ""


def test_parse_latest_tag_no_match():
    assert _parse_latest_tag("abc123\trefs/tags/v1.0.0\n") == ""


def test_get_local_version():
    v = _get_local_version()
    assert v  # should return something since termiclaw is installed


def test_start_update_check():
    proc = _start_update_check()
    if proc is not None:
        proc.kill()
        proc.wait()


def test_finish_update_check_none():
    _finish_update_check(None)  # should not raise


def test_finish_update_check_no_update(capsys):
    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b"abc\trefs/tags/termiclaw-v0.0.1\n"
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.returncode = 0
    mock_proc.stdout = mock_stdout
    _finish_update_check(mock_proc)
    captured = capsys.readouterr()
    assert "Update available" not in captured.err


def test_finish_update_check_with_update(capsys):
    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b"abc\trefs/tags/termiclaw-v99.0.0\n"
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.returncode = 0
    mock_proc.stdout = mock_stdout
    _finish_update_check(mock_proc)
    captured = capsys.readouterr()
    assert "Update available" in captured.err
    assert "99.0.0" in captured.err


def test_finish_update_check_still_running():
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # still running
    _finish_update_check(mock_proc)  # should return immediately, no block
