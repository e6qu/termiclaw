"""Tests for termiclaw.stall."""

from __future__ import annotations

from dataclasses import replace

from termiclaw.models import Config, ParsedCommand
from termiclaw.stall import (
    ScreenClass,
    StallSignal,
    classify_screen,
    detect_stall,
    hint_for,
    normalize_for_stall,
    nudge_text,
)
from termiclaw.state import State


def _state() -> State:
    return State(
        run_id="r",
        instruction="task",
        tmux_session="s",
        started_at="t",
        status="active",
    )


def _step(state: State, output: str, cmd: tuple[ParsedCommand, ...], config: Config):
    """Run detect_stall once, re-thread the new stall into the state, return signal."""
    new_stall, signal = detect_stall(state, output, cmd, config)
    return replace(state, stall=new_stall), signal


def test_normalize_strips_timestamps():
    a = normalize_for_stall("build at 12:34:56 done")
    b = normalize_for_stall("build at 09:00:00 done")
    assert a == b


def test_normalize_strips_pids():
    a = normalize_for_stall("process pid=1234 running")
    b = normalize_for_stall("process pid=9999 running")
    assert a == b


def test_normalize_strips_counters():
    a = normalize_for_stall("downloaded 5/10 files")
    b = normalize_for_stall("downloaded 9/10 files")
    assert a == b


def test_normalize_strips_durations():
    a = normalize_for_stall("took 123ms")
    b = normalize_for_stall("took 456ms")
    assert a == b


def test_normalize_strips_hex_addresses():
    a = normalize_for_stall("segfault at 0xdeadbeef")
    b = normalize_for_stall("segfault at 0xcafebabe")
    assert a == b


def test_normalize_preserves_non_volatile():
    a = normalize_for_stall("hello world")
    assert a == "hello world"


def test_classify_vim():
    assert classify_screen("-- INSERT --") == ScreenClass.VIM


def test_classify_less():
    assert classify_screen("some text\n:\n") == ScreenClass.LESS


def test_classify_repl_python():
    assert classify_screen(">>> x = 1\n>>> ") == ScreenClass.REPL


def test_classify_confirmation():
    assert classify_screen("Overwrite? [Y/n]") == ScreenClass.CONFIRMATION


def test_classify_debugger():
    assert classify_screen("(gdb) ") == ScreenClass.DEBUGGER


def test_classify_idle_shell():
    assert classify_screen("$ ") == ScreenClass.IDLE_SHELL


def test_classify_unknown():
    assert classify_screen("random output") == ScreenClass.UNKNOWN


def test_hint_for_less():
    assert "q" in hint_for(ScreenClass.LESS).lower()


def test_hint_for_unknown_is_empty():
    assert hint_for(ScreenClass.UNKNOWN) == ""


def test_no_stall_on_fresh_state():
    state = _state()
    config = Config(instruction="t")
    cmd = (ParsedCommand(keystrokes="ls\n", duration=0.1),)
    _, signal = detect_stall(state, "output", cmd, config)
    assert signal == StallSignal.NONE


def test_stall_nudge_on_repeat_commands():
    state = _state()
    config = Config(instruction="t", stall_nudge_after=2, stall_force_interrupt_after=4)
    cmd = (ParsedCommand(keystrokes="ls\n", duration=0.1),)
    state, sig = _step(state, "out1", cmd, config)
    assert sig == StallSignal.NONE
    state, sig = _step(state, "out2", cmd, config)
    assert sig == StallSignal.NONE
    state, sig = _step(state, "out3", cmd, config)
    assert sig == StallSignal.NUDGE_REPEAT


def test_stall_force_interrupt_on_sustained_repeat():
    state = _state()
    config = Config(instruction="t", stall_nudge_after=2, stall_force_interrupt_after=4)
    cmd = (ParsedCommand(keystrokes="ls\n", duration=0.1),)
    for _ in range(4):
        state, _ = _step(state, "out", cmd, config)
    _, sig = _step(state, "out", cmd, config)
    assert sig == StallSignal.FORCE_INTERRUPT


def test_stall_normalizes_before_compare():
    state = _state()
    config = Config(instruction="t", stall_nudge_after=2, stall_force_interrupt_after=4)
    cmd = (ParsedCommand(keystrokes="ls\n", duration=0.1),)
    state, sig = _step(state, "done at 12:34:56", cmd, config)
    assert sig == StallSignal.NONE
    state, sig = _step(state, "done at 09:00:00", cmd, config)
    assert sig == StallSignal.NONE
    state, sig = _step(state, "done at 01:02:03", cmd, config)
    assert sig == StallSignal.NUDGE_REPEAT


def test_nudge_text_repeat_mentions_streak():
    text = nudge_text(StallSignal.NUDGE_REPEAT, 3)
    assert "3 turns" in text


def test_nudge_text_none_is_empty():
    assert nudge_text(StallSignal.NONE, 0) == ""
