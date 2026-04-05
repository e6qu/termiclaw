"""Tests for termiclaw.trajectory."""

import json

from termiclaw.models import ParsedCommand, RunState, StepRecord
from termiclaw.trajectory import (
    append_step,
    ensure_run_dir,
    read_trajectory_text,
    write_run_metadata,
)


def test_ensure_run_dir_creates(tmp_path):
    run_dir = ensure_run_dir(str(tmp_path / "runs"), "abc123")
    assert run_dir.exists()
    assert run_dir.name == "abc123"


def test_ensure_run_dir_idempotent(tmp_path):
    runs = str(tmp_path / "runs")
    d1 = ensure_run_dir(runs, "abc")
    d2 = ensure_run_dir(runs, "abc")
    assert d1 == d2
    assert d1.exists()


def test_append_step_creates_file(tmp_path):
    step = StepRecord(
        step_id="s1",
        timestamp="2026-04-05T00:00:00Z",
        source="agent",
        observation="output",
    )
    append_step(tmp_path, step)
    trajectory = tmp_path / "trajectory.jsonl"
    assert trajectory.exists()
    lines = trajectory.read_text().strip().splitlines()
    assert len(lines) == 1


def test_append_step_appends(tmp_path):
    for i in range(3):
        step = StepRecord(
            step_id=f"s{i}",
            timestamp="t",
            source="agent",
            observation="out",
        )
        append_step(tmp_path, step)
    lines = (tmp_path / "trajectory.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3


def test_append_step_atif_format(tmp_path):
    cmd = ParsedCommand(keystrokes="ls\n", duration=0.5)
    step = StepRecord(
        step_id="s1",
        timestamp="t",
        source="agent",
        observation="out",
        analysis="shell idle",
        commands=(cmd,),
    )
    append_step(tmp_path, step)
    line = (tmp_path / "trajectory.jsonl").read_text().strip()
    data = json.loads(line)
    assert data["step_id"] == "s1"
    assert data["message"] == "shell idle"
    assert len(data["tool_calls"]) == 1
    assert data["tool_calls"][0]["function_name"] == "bash_command"
    assert data["tool_calls"][0]["arguments"]["keystrokes"] == "ls\n"
    assert data["observation"]["terminal_output"] == "out"


def test_append_step_task_complete(tmp_path):
    step = StepRecord(
        step_id="s1",
        timestamp="t",
        source="agent",
        observation="out",
        task_complete=True,
    )
    append_step(tmp_path, step)
    line = (tmp_path / "trajectory.jsonl").read_text().strip()
    data = json.loads(line)
    assert data["tool_calls"][0]["function_name"] == "mark_task_complete"


def test_write_run_metadata(tmp_path):
    state = RunState(
        run_id="abc",
        instruction="fix bug",
        tmux_session="termiclaw-abc",
        started_at="2026-04-05T00:00:00Z",
        status="succeeded",
        current_step=10,
    )
    write_run_metadata(
        tmp_path, state, finished_at="2026-04-05T00:05:00Z", termination_reason="task_complete"
    )
    data = json.loads((tmp_path / "run.json").read_text())
    assert data["run_id"] == "abc"
    assert data["instruction"] == "fix bug"
    assert data["total_steps"] == 10
    assert data["termination_reason"] == "task_complete"


def test_write_run_metadata_overwrite(tmp_path):
    state = RunState(
        run_id="abc",
        instruction="x",
        tmux_session="t",
        started_at="t",
        status="active",
    )
    write_run_metadata(tmp_path, state)
    state.status = "succeeded"
    write_run_metadata(tmp_path, state, finished_at="done")
    data = json.loads((tmp_path / "run.json").read_text())
    assert data["status"] == "succeeded"
    assert data["finished_at"] == "done"


def test_step_metrics_serialized(tmp_path):
    step = StepRecord(
        step_id="s1",
        timestamp="t",
        source="agent",
        observation="out",
        metrics=(("prompt_chars", 1500), ("duration_ms", 3200)),
    )
    append_step(tmp_path, step)
    line = (tmp_path / "trajectory.jsonl").read_text().strip()
    data = json.loads(line)
    assert data["metrics"]["prompt_chars"] == 1500
    assert data["metrics"]["duration_ms"] == 3200


def test_read_trajectory_text_empty(tmp_path):
    assert read_trajectory_text(tmp_path) == ""


def test_read_trajectory_text_returns_content(tmp_path):
    for i in range(3):
        step = StepRecord(
            step_id=f"step{i}xxx",
            timestamp="t",
            source="agent",
            observation=f"output {i}",
            analysis=f"analysis {i}",
        )
        append_step(tmp_path, step)
    text = read_trajectory_text(tmp_path)
    assert "step0xxx" in text
    assert "analysis 2" in text


def test_read_trajectory_text_respects_max_chars(tmp_path):
    for i in range(100):
        step = StepRecord(
            step_id=f"s{i:04d}xxxx",
            timestamp="t",
            source="agent",
            observation="x" * 500,
            analysis=f"step {i}",
        )
        append_step(tmp_path, step)
    text = read_trajectory_text(tmp_path, max_chars=1000)
    assert len(text) <= 1200  # some slack for last entry
