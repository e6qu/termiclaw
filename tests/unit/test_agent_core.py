"""Tests for termiclaw.agent_core — pure decision helpers, no mocks needed."""

from __future__ import annotations

from termiclaw.agent_core import (
    apply_nudge,
    artifact_refresh_trigger,
    clamp_command_wait,
    detect_stall_for_commands,
    forced_interrupt_exhausted,
    format_blocking_timeout_notice,
    format_completion_confirmation_prompt,
    format_force_interrupt_notice,
    format_nudge_for_observation,
    prepend_screen_hint,
    should_force_interrupt,
    should_summarize,
    termination_reason,
)
from termiclaw.models import Config, ParsedCommand
from termiclaw.stall import StallSignal
from termiclaw.state import StallState, State


def _state(
    tokens: int = 0,
    step: int = 0,
    forced_interrupts: int = 0,
    repeat_streak: int = 0,
    identical_streak: int = 0,
) -> State:
    return State(
        run_id="r",
        instruction="t",
        tmux_session="s",
        started_at="t",
        status="active",
        total_prompt_tokens=tokens,
        current_step=step,
        stall=StallState(
            forced_interrupts=forced_interrupts,
            repeat_command_streak=repeat_streak,
            identical_obs_streak=identical_streak,
        ),
    )


def test_should_summarize_under_threshold():
    config = Config(instruction="t", summarization_token_threshold=100)
    assert should_summarize(_state(tokens=50), config) is False


def test_should_summarize_at_threshold():
    config = Config(instruction="t", summarization_token_threshold=100)
    assert should_summarize(_state(tokens=100), config) is True


def test_should_summarize_over_threshold():
    config = Config(instruction="t", summarization_token_threshold=100)
    assert should_summarize(_state(tokens=150), config) is True


def test_artifact_refresh_skip_at_step_zero():
    config = Config(instruction="t", state_dump_interval_turns=10)
    assert artifact_refresh_trigger(_state(step=0), config) == ""


def test_artifact_refresh_interval():
    config = Config(
        instruction="t",
        state_dump_interval_turns=10,
        state_dump_token_threshold=10_000_000,
    )
    assert artifact_refresh_trigger(_state(step=10), config) == "interval"
    assert artifact_refresh_trigger(_state(step=20), config) == "interval"
    assert artifact_refresh_trigger(_state(step=11), config) == ""


def test_artifact_refresh_token_threshold():
    config = Config(
        instruction="t",
        state_dump_interval_turns=1000,
        state_dump_token_threshold=1000,
    )
    assert artifact_refresh_trigger(_state(step=5, tokens=1500), config) == "token_threshold"


def test_should_force_interrupt_respects_budget():
    config = Config(instruction="t", max_forced_interrupts_per_run=5)
    assert (
        should_force_interrupt(
            _state(forced_interrupts=0),
            config,
            StallSignal.FORCE_INTERRUPT,
        )
        is True
    )
    assert (
        should_force_interrupt(
            _state(forced_interrupts=5),
            config,
            StallSignal.FORCE_INTERRUPT,
        )
        is False
    )


def test_should_force_interrupt_only_on_force_signal():
    config = Config(instruction="t")
    assert should_force_interrupt(_state(), config, StallSignal.NONE) is False
    assert should_force_interrupt(_state(), config, StallSignal.NUDGE_REPEAT) is False


def test_forced_interrupt_exhausted():
    config = Config(instruction="t", max_forced_interrupts_per_run=3)
    assert (
        forced_interrupt_exhausted(
            _state(forced_interrupts=3),
            config,
            StallSignal.FORCE_INTERRUPT,
        )
        is True
    )
    assert (
        forced_interrupt_exhausted(
            _state(forced_interrupts=2),
            config,
            StallSignal.FORCE_INTERRUPT,
        )
        is False
    )
    assert (
        forced_interrupt_exhausted(
            _state(forced_interrupts=5),
            config,
            StallSignal.NONE,
        )
        is False
    )


def test_format_nudge_repeat():
    text = format_nudge_for_observation(StallSignal.NUDGE_REPEAT, _state(repeat_streak=3))
    assert "3 turns" in text


def test_format_nudge_no_progress():
    text = format_nudge_for_observation(
        StallSignal.NUDGE_NO_PROGRESS,
        _state(identical_streak=4),
    )
    assert "4 turns" in text


def test_format_nudge_none():
    assert format_nudge_for_observation(StallSignal.NONE, _state()) == ""


def test_apply_nudge_prepends():
    result = apply_nudge("output", StallSignal.NUDGE_REPEAT, _state(repeat_streak=2))
    assert result.endswith("output")
    assert "2 turns" in result


def test_apply_nudge_noop_on_none():
    assert apply_nudge("output", StallSignal.NONE, _state()) == "output"


def test_format_force_interrupt_notice_mentions_threshold():
    config = Config(instruction="t", stall_force_interrupt_after=4)
    text = format_force_interrupt_notice(config)
    assert "4 turns" in text
    assert "C-c" in text


def test_format_blocking_timeout_notice_mentions_budget():
    config = Config(instruction="t", blocking_max_seconds=60.0)
    text = format_blocking_timeout_notice(config)
    assert "60" in text


def test_confirmation_prompt_contains_visible_screen():
    text = format_completion_confirmation_prompt("$ ls -la")
    assert "$ ls -la" in text
    assert "task_complete=true" in text


def test_prepend_screen_hint_with_match():
    # The stall.classify_screen detects "less" on a lone colon prompt.
    result = prepend_screen_hint("long output\n:\n")
    assert result.startswith("[HINT:")


def test_prepend_screen_hint_no_match():
    # Random text classifies as UNKNOWN → no hint.
    result = prepend_screen_hint("abstract text with no shell markers")
    assert result == "abstract text with no shell markers"


def test_termination_reason_cases():
    assert termination_reason("succeeded") == "task_complete_confirmed"
    assert termination_reason("cancelled") == "keyboard_interrupt"
    assert termination_reason("failed") == "max_turns_or_failure"
    assert termination_reason("weird") == "unknown"


def test_clamp_command_wait_duration_under_cap():
    cmd = ParsedCommand(keystrokes="ls", duration=5.0)
    assert clamp_command_wait(cmd, 60.0) == 5.0


def test_clamp_command_wait_duration_over_cap():
    cmd = ParsedCommand(keystrokes="make", duration=300.0)
    assert clamp_command_wait(cmd, 60.0) == 60.0


def test_clamp_command_wait_zero_duration_uses_cap():
    cmd = ParsedCommand(keystrokes="ls", duration=0.0)
    assert clamp_command_wait(cmd, 60.0) == 60.0


def test_detect_stall_for_commands_passes_through():
    state = _state()
    config = Config(instruction="t")
    cmd = (ParsedCommand(keystrokes="ls\n", duration=0.1),)
    _new_stall, signal = detect_stall_for_commands(state, "output", cmd, config)
    assert signal == StallSignal.NONE
