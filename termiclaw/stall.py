"""Stall detection: normalize terminal state + detect repeat/no-progress loops."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from termiclaw.models import Config, ParsedCommand
    from termiclaw.state import StallState, State


_VOLATILE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?"), "TS"),
    (re.compile(r"\bpid[=: ]?\d+", re.IGNORECASE), "PID"),
    (re.compile(r"\b\d+/\d+\b"), "N/N"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|KB|MB|GB|KiB|MiB|GiB)\b"), "DUR"),
    (re.compile(r"0x[0-9a-fA-F]{6,}"), "ADDR"),
)


def normalize_for_stall(text: str) -> str:
    """Collapse volatile patterns so near-duplicate outputs hash equally."""
    result = text.strip()
    for pattern, placeholder in _VOLATILE_PATTERNS:
        result = pattern.sub(placeholder, result)
    return result


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class ScreenClass(StrEnum):
    """Coarse classification of the visible terminal state."""

    IDLE_SHELL = "idle_shell"
    LESS = "less"
    VIM = "vim"
    REPL = "repl"
    CONFIRMATION = "confirmation"
    DEBUGGER = "debugger"
    UNKNOWN = "unknown"


_SCREEN_CLASSIFIERS: tuple[tuple[re.Pattern[str], ScreenClass], ...] = (
    (re.compile(r"^:\s*$", re.MULTILINE), ScreenClass.LESS),
    (re.compile(r"^-- INSERT --|^-- NORMAL --|^:(q|w|wq|x)", re.MULTILINE), ScreenClass.VIM),
    (re.compile(r"^(>>>|In \[\d+\]:|\.\.\.)", re.MULTILINE), ScreenClass.REPL),
    (
        re.compile(r"\[[Yy]/[Nn]\]|\(y/n\)|\(yes/no\)|Proceed\?|Continue\?"),
        ScreenClass.CONFIRMATION,
    ),
    (re.compile(r"^\((gdb|lldb|Pdb|pdb)\)\s*$", re.MULTILINE), ScreenClass.DEBUGGER),
)


def classify_screen(visible: str) -> ScreenClass:
    """Identify the program the terminal appears to be inside."""
    for pattern, screen_class in _SCREEN_CLASSIFIERS:
        if pattern.search(visible):
            return screen_class
    return ScreenClass.IDLE_SHELL if "$" in visible or "#" in visible else ScreenClass.UNKNOWN


def hint_for(screen_class: ScreenClass) -> str:
    """Return a one-line hint for how to exit an interactive program."""
    hints = {
        ScreenClass.LESS: "The terminal appears to be inside 'less'. Press 'q' to exit.",
        ScreenClass.VIM: (
            "The terminal appears to be inside 'vim'. Press Escape then ':q!' to quit "
            "without saving, or ':wq' to save and quit."
        ),
        ScreenClass.REPL: (
            "The terminal appears to be inside a REPL. Press Ctrl-D or type 'exit()' "
            "to return to the shell."
        ),
        ScreenClass.CONFIRMATION: (
            "The terminal is waiting on a confirmation prompt. Answer 'y' or 'n' and press Enter."
        ),
        ScreenClass.DEBUGGER: (
            "The terminal appears to be inside a debugger. Type 'quit' or press Ctrl-D to exit."
        ),
    }
    return hints.get(screen_class, "")


class StallSignal(StrEnum):
    """What the agent loop should do in response to a stall check."""

    NONE = "none"
    NUDGE_REPEAT = "nudge_repeat"
    NUDGE_NO_PROGRESS = "nudge_no_progress"
    FORCE_INTERRUPT = "force_interrupt"


def detect_stall(
    state: State,
    observation: str,
    commands: Sequence[ParsedCommand],
    config: Config,
) -> tuple[StallState, StallSignal]:
    """Pure: compute the new StallState and the appropriate response signal."""
    obs_hash = _hash(normalize_for_stall(observation))
    cmd_hash = _hash("\n".join(c.keystrokes for c in commands))
    old = state.stall

    new_obs_streak = (
        old.identical_obs_streak + 1
        if obs_hash == old.last_observation_hash and old.last_observation_hash
        else 0
    )
    new_cmd_streak = (
        old.repeat_command_streak + 1 if cmd_hash == old.last_keystrokes_hash and cmd_hash else 0
    )

    new_stall = replace(
        old,
        identical_obs_streak=new_obs_streak,
        repeat_command_streak=new_cmd_streak,
        last_observation_hash=obs_hash,
        last_keystrokes_hash=cmd_hash,
    )

    force_threshold = config.stall_force_interrupt_after
    if new_cmd_streak >= force_threshold or new_obs_streak >= force_threshold:
        signal = StallSignal.FORCE_INTERRUPT
    elif new_cmd_streak >= config.stall_nudge_after:
        signal = StallSignal.NUDGE_REPEAT
    elif new_obs_streak >= config.stall_nudge_after:
        signal = StallSignal.NUDGE_NO_PROGRESS
    else:
        signal = StallSignal.NONE
    return (new_stall, signal)


def nudge_text(signal: StallSignal, streak: int) -> str:
    """Return the system-notice text to prepend to the next observation."""
    if signal == StallSignal.NUDGE_REPEAT:
        return (
            f"[SYSTEM NOTICE: You have sent the same command {streak} turns in a row "
            "and the terminal has not changed. Try a different approach — inspect "
            "what actually happened, change the command, or send C-c to interrupt "
            "and retry.]\n"
        )
    if signal == StallSignal.NUDGE_NO_PROGRESS:
        return (
            f"[SYSTEM NOTICE: The terminal output has not changed for {streak} turns. "
            "If a command is running, interrupt it with C-c and investigate. If you "
            "are inside an interactive program, exit it first.]\n"
        )
    return ""
