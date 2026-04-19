"""Tests for termiclaw.db."""

from dataclasses import replace

from termiclaw.db import (
    get_run,
    get_steps,
    get_usage_summary,
    init_db,
    insert_run,
    insert_step,
    list_runs_from_db,
    update_run,
)
from termiclaw.models import ParsedCommand, StepRecord
from termiclaw.state import RunStatus, State


def _make_state(run_id: str = "abc123", status: RunStatus = "active") -> State:
    return State(
        run_id=run_id,
        instruction="test task",
        tmux_session=f"t-{run_id}",
        started_at="2026-04-06T00:00:00+00:00",
        status=status,
    )


def test_init_db(tmp_path):
    conn = init_db(tmp_path / "test.db")
    assert conn is not None
    conn.close()


def test_insert_and_list_runs(tmp_path):
    conn = init_db(tmp_path / "test.db")
    s1 = _make_state("run1")
    s2 = replace(_make_state("run2"), started_at="2026-04-06T01:00:00+00:00")
    insert_run(conn, s1)
    insert_run(conn, s2)
    runs = list_runs_from_db(conn)
    assert len(runs) == 2
    assert runs[0].run_id == "run2"  # newest first
    conn.close()


def test_update_run(tmp_path):
    conn = init_db(tmp_path / "test.db")
    state = _make_state()
    insert_run(conn, state)
    state = replace(state, status="succeeded", current_step=5)
    update_run(
        conn,
        state,
        finished_at="2026-04-06T00:05:00+00:00",
        termination_reason="done",
        total_prompt_tokens=10000,
        total_input_tokens=500,
        total_output_tokens=200,
        total_cost_usd=0.05,
    )
    run = get_run(conn, "abc")
    assert run is not None
    assert run.status == "succeeded"
    assert run.total_steps == 5
    assert run.input_tokens == 500
    assert run.cost_usd == 0.05
    conn.close()


def test_insert_step(tmp_path):
    conn = init_db(tmp_path / "test.db")
    state = _make_state()
    insert_run(conn, state)
    cmd = ParsedCommand(keystrokes="ls\n", duration=0.5)
    step = StepRecord(
        step_id="step1",
        timestamp="2026-04-06T00:00:01+00:00",
        source="agent",
        observation="output",
        analysis="checking",
        commands=(cmd,),
        metrics=(("prompt_tokens", 1500),),
    )
    insert_step(
        conn,
        "abc123",
        step,
        step_index=0,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.01,
        planner_duration_ms=500,
    )
    steps = get_steps(conn, "abc123")
    assert len(steps) == 1
    assert steps[0]["analysis"] == "checking"
    assert steps[0]["input_tokens"] == 100
    cmds = steps[0]["commands"]
    assert isinstance(cmds, list)
    assert len(cmds) == 1
    conn.close()


def test_get_run_by_prefix(tmp_path):
    conn = init_db(tmp_path / "test.db")
    insert_run(conn, _make_state("abcdef123456"))
    run = get_run(conn, "abcdef")
    assert run is not None
    assert run.run_id == "abcdef123456"
    conn.close()


def test_get_run_not_found(tmp_path):
    conn = init_db(tmp_path / "test.db")
    assert get_run(conn, "nonexistent") is None
    conn.close()


def test_get_usage_summary(tmp_path):
    conn = init_db(tmp_path / "test.db")
    s1 = _make_state("r1", status="succeeded")
    s2 = _make_state("r2", status="failed")
    insert_run(conn, s1)
    insert_run(conn, s2)
    s1 = replace(s1, current_step=3)
    s2 = replace(s2, current_step=1)
    update_run(
        conn,
        s1,
        finished_at="t",
        termination_reason="done",
        total_prompt_tokens=5000,
        total_input_tokens=200,
        total_output_tokens=100,
        total_cost_usd=0.03,
    )
    update_run(
        conn,
        s2,
        finished_at="t",
        termination_reason="err",
        total_prompt_tokens=1000,
        total_input_tokens=50,
        total_output_tokens=20,
        total_cost_usd=0.01,
    )
    summary = get_usage_summary(conn)
    assert summary["total_runs"] == 2
    assert summary["succeeded"] == 1
    assert summary["failed"] == 1
    assert summary["total_input_tokens"] == 250
    assert summary["total_cost_usd"] == 0.04
    conn.close()


def test_get_steps_empty(tmp_path):
    conn = init_db(tmp_path / "test.db")
    assert get_steps(conn, "nonexistent") == []
    conn.close()
