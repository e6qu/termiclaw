"""Smoke tests for `termiclaw.runtime` default ports — narrow coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from termiclaw.models import Config, PlannerUsage, StepRecord
from termiclaw.runtime import (
    DefaultArtifactsPort,
    DefaultContainerPort,
    DefaultPersistencePort,
    DefaultPlannerPort,
    DefaultSummarizePort,
    build_default_ports,
)
from termiclaw.state import State
from termiclaw.summarize_worker import SummarizationWorker


def _state() -> State:
    return State(
        run_id="r",
        instruction="t",
        tmux_session="s",
        started_at="s",
        status="active",
        container_id="c",
        claude_session_id="sess",
    )


def test_default_container_port_delegates_tail_and_truncate():
    port = DefaultContainerPort()
    assert port.tail_bytes("abcdefg", 3) == "efg"
    out = port.truncate_output("x" * 100, max_bytes=10)
    assert len(out) <= 10 or "truncated" in out


def test_default_planner_port_build_prompt():
    port = DefaultPlannerPort()
    prompt = port.build_prompt("do X", "$ ", None, None)
    assert "do X" in prompt


def test_default_persistence_port_roundtrips(tmp_db_path):
    _ = tmp_db_path
    conn = sqlite3.connect(str(tmp_db_path))
    # Manually create the schema via the real db module.
    from termiclaw.db import init_db  # noqa: PLC0415 — isolate

    conn.close()
    conn = init_db(tmp_db_path)
    port = DefaultPersistencePort(conn)
    state = _state()
    port.insert_run(state)
    port.update_run(
        state,
        finished_at="f",
        termination_reason="done",
        total_prompt_tokens=1,
        total_input_tokens=2,
        total_output_tokens=3,
        total_cost_usd=0.1,
    )
    step = StepRecord(
        step_id="s1",
        timestamp="t",
        source="agent",
        observation="x",
    )
    port.insert_step(
        state.run_id,
        step,
        step_index=0,
        input_tokens=1,
        output_tokens=0,
        cost_usd=0.0,
        planner_duration_ms=10,
    )
    usage = port.aggregate_usage(state.run_id)
    assert isinstance(usage, PlannerUsage)
    port.close()


def test_default_artifacts_port_has_config(tmp_path):
    _ = tmp_path
    cfg = Config(instruction="t")

    def _visible(state: State) -> str:
        _ = state
        return "screen"

    port = DefaultArtifactsPort(cfg, _visible)
    assert port._config is cfg  # noqa: SLF001 — smoke


def test_default_summarize_port_delegates_lifecycle():
    def _query(_prompt: str) -> str:
        return ""

    worker = SummarizationWorker(query_fn=_query)
    port = DefaultSummarizePort(worker)
    assert port.idle() is True
    assert port.poll() is None
    port.shutdown()


def test_build_default_ports_wires_everything(tmp_db_path):
    from termiclaw.db import init_db  # noqa: PLC0415

    conn = init_db(tmp_db_path)

    def _query(_prompt: str) -> str:
        return ""

    bundle = build_default_ports(Config(instruction="t"), conn, _query)
    assert bundle.container is not None
    assert bundle.planner is not None
    assert bundle.persistence is not None
    assert bundle.artifacts is not None
    assert bundle.summarize is not None
    bundle.summarize.shutdown()
    conn.close()
    _ = Path  # unused-import guard
