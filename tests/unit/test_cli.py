"""Tests for termiclaw.cli."""

import argparse
import subprocess
from unittest.mock import patch

import pytest

from termiclaw.cli import _attach, _check_claude, _check_tmux, _run


def test_check_tmux_present():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _check_tmux()  # should not raise


def test_check_tmux_missing():
    with (
        patch("termiclaw.cli.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(SystemExit),
    ):
        _check_tmux()


def test_check_claude_present():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _check_claude()  # should not raise


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
