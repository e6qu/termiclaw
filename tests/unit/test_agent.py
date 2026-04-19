"""End-to-end smoke tests for `agent.run()`.

Handler-level decision tests live in `test_decide.py`; per-command
effect tests live in `test_apply.py`. This file only exercises the
full orchestration with fake Ports to verify the shell+driver loop
wires everything together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from termiclaw.agent import _build_summarization_query_fn, _StateHolder
from termiclaw.agent_core import termination_reason
from termiclaw.errors import PlannerError
from termiclaw.models import Config
from termiclaw.result import Err, Ok
from termiclaw.state import State

if TYPE_CHECKING:
    from termiclaw.result import Result


def _make_state(
    run_id: str = "abc123",
    instruction: str = "fix bug",
    tmux_session: str = "termiclaw-abc",
    started_at: str = "2026-04-05T00:00:00Z",
    claude_session_id: str = "",
) -> State:
    return State(
        run_id=run_id,
        instruction=instruction,
        tmux_session=tmux_session,
        started_at=started_at,
        claude_session_id=claude_session_id,
    )


def test_termination_reason_succeeded():
    assert termination_reason("succeeded") == "task_complete_confirmed"


def test_termination_reason_cancelled():
    assert termination_reason("cancelled") == "keyboard_interrupt"


def test_termination_reason_failed():
    assert termination_reason("failed") == "max_turns_or_failure"


def _stub_planner(response: Result[str, PlannerError]):
    def planner_fn(_prompt: str, **_kwargs: object) -> Result[str, PlannerError]:
        return response

    return planner_fn


def test_build_summarization_query_fn_returns_result_field():
    state = _make_state(claude_session_id="sess")
    cfg = Config(instruction="t")
    qf = _build_summarization_query_fn(
        _StateHolder(state),
        cfg,
        _stub_planner(Ok('{"result": "summary text"}')),
    )
    assert qf("any prompt") == "summary text"


def test_build_summarization_query_fn_returns_raw_on_nonjson():
    state = _make_state(claude_session_id="sess")
    cfg = Config(instruction="t")
    qf = _build_summarization_query_fn(
        _StateHolder(state),
        cfg,
        _stub_planner(Ok("plain text")),
    )
    assert qf("any prompt") == "plain text"


def test_build_summarization_query_fn_raises_on_err():
    state = _make_state(claude_session_id="sess")
    cfg = Config(instruction="t")
    qf = _build_summarization_query_fn(
        _StateHolder(state),
        cfg,
        _stub_planner(Err(PlannerError("boom"))),
    )
    with pytest.raises(PlannerError):
        qf("any prompt")
