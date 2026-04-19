"""Tests for termiclaw.state helpers."""

from __future__ import annotations

from dataclasses import replace

from termiclaw.models import ParsedCommand, StepRecord
from termiclaw.state import (
    ForkContext,
    StallState,
    State,
    coerce_status,
    with_stall,
    with_stall_counters,
    with_status,
    with_step,
    with_summarization,
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


def _step(step_id: str = "s1") -> StepRecord:
    return StepRecord(step_id=step_id, timestamp="t", source="agent", observation="x")


def test_coerce_status_active():
    assert coerce_status("active") == "active"


def test_coerce_status_succeeded():
    assert coerce_status("succeeded") == "succeeded"


def test_coerce_status_cancelled():
    assert coerce_status("cancelled") == "cancelled"


def test_coerce_status_failed_default():
    assert coerce_status("failed") == "failed"
    assert coerce_status("garbage") == "failed"


def test_with_step_increments_and_appends():
    state = _state(current_step=0)
    state = with_step(state, _step("s1"))
    assert state.current_step == 1
    assert len(state.recent_steps) == 1


def test_with_step_trims_ring_buffer():
    state = _state()
    for i in range(25):
        state = with_step(state, _step(f"s{i}"))
    assert state.current_step == 25
    assert len(state.recent_steps) == 20
    assert state.recent_steps[0].step_id == "s5"


def test_with_status_transitions():
    state = _state()
    state = with_status(state, "succeeded")
    assert state.status == "succeeded"


def test_with_summarization_resets_tokens_and_steps():
    state = _state(total_prompt_tokens=1000, recent_steps=(_step(),))
    state = with_summarization(state, "summary", "qa")
    assert state.summary == "summary"
    assert state.qa_context == "qa"
    assert state.total_prompt_tokens == 0
    assert state.recent_steps == ()


def test_with_stall_replaces_wholesale():
    state = _state()
    new = StallState(nudges_sent=7)
    state = with_stall(state, new)
    assert state.stall.nudges_sent == 7


def test_with_stall_counters_partial_update():
    state = _state()
    state = with_stall_counters(state, nudges_sent=3)
    assert state.stall.nudges_sent == 3
    assert state.stall.forced_interrupts == 0


def test_with_stall_counters_multiple_fields():
    state = _state()
    state = with_stall_counters(
        state,
        identical_obs_streak=1,
        repeat_command_streak=2,
        last_keystrokes_hash="ab",
        last_observation_hash="cd",
        nudges_sent=3,
        forced_interrupts=4,
    )
    assert state.stall.identical_obs_streak == 1
    assert state.stall.repeat_command_streak == 2
    assert state.stall.last_keystrokes_hash == "ab"
    assert state.stall.last_observation_hash == "cd"
    assert state.stall.nudges_sent == 3
    assert state.stall.forced_interrupts == 4


def test_fork_context_fields():
    fork = ForkContext(parent_run_id="p", forked_at_step=3, resume_parent_session="sess")
    assert fork.parent_run_id == "p"
    assert fork.forked_at_step == 3
    assert fork.resume_parent_session == "sess"


def test_state_with_fork():
    fork = ForkContext(parent_run_id="p", forked_at_step=1, resume_parent_session="s")
    state = _state(fork=fork)
    assert state.fork is not None
    assert state.fork.parent_run_id == "p"
    # ParsedCommand present ensures we didn't inadvertently break any other dataclass.
    _ = ParsedCommand(keystrokes="x", duration=1.0)
