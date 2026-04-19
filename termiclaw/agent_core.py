"""Functional core: pure decision functions called by the imperative shell.

These functions read state and config but perform no I/O, no subprocess
calls, no datetime.now(), no sleep, no logging. They are deterministic
given their inputs and fully unit-testable without mocks.

The shell (`agent.py::_run_loop`) owns side effects; it calls these
helpers to decide *what* to do, then does it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from termiclaw import stall
from termiclaw.stall import StallSignal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from termiclaw.models import Config, ParsedCommand
    from termiclaw.state import StallState, State


def should_summarize(state: State, config: Config) -> bool:
    """Pure check: has the token-accumulator hit the summarization threshold?"""
    return state.total_prompt_tokens >= config.summarization_token_threshold


def artifact_refresh_trigger(state: State, config: Config) -> str:
    """Pure check: return the refresh trigger name, or empty string if none."""
    if state.current_step == 0:
        return ""
    if state.current_step % config.state_dump_interval_turns == 0:
        return "interval"
    if state.total_prompt_tokens >= config.state_dump_token_threshold:
        return "token_threshold"
    return ""


def should_force_interrupt(
    state: State,
    config: Config,
    signal: StallSignal,
) -> bool:
    """Pure check: should the loop send C-c right now?"""
    if signal != StallSignal.FORCE_INTERRUPT:
        return False
    return state.stall.forced_interrupts < config.max_forced_interrupts_per_run


def forced_interrupt_exhausted(state: State, config: Config, signal: StallSignal) -> bool:
    """Pure check: the agent is stuck AND we've exhausted the interrupt budget."""
    if signal != StallSignal.FORCE_INTERRUPT:
        return False
    return state.stall.forced_interrupts >= config.max_forced_interrupts_per_run


def format_nudge_for_observation(
    signal: StallSignal,
    state: State,
) -> str:
    """Pure: return the system-notice text to prepend to the next observation."""
    if signal == StallSignal.NUDGE_REPEAT:
        return stall.nudge_text(signal, state.stall.repeat_command_streak)
    if signal == StallSignal.NUDGE_NO_PROGRESS:
        return stall.nudge_text(signal, state.stall.identical_obs_streak)
    return ""


def format_force_interrupt_notice(config: Config) -> str:
    """Pure: the notice injected when we force a C-c interrupt."""
    return (
        f"[SYSTEM NOTICE: I sent C-c because you appeared stuck for "
        f"{config.stall_force_interrupt_after} turns. If you are inside an "
        "interactive program, exit it and reassess.]\n"
    )


def format_blocking_timeout_notice(config: Config) -> str:
    """Pure: the notice for a command that exceeded blocking_max_seconds."""
    return (
        f"[SYSTEM NOTICE: Your command ran for more than "
        f"{config.blocking_max_seconds}s without emitting the completion "
        "marker. It may still be running or it may be hung. Consider C-c "
        "if it is stuck.]\n"
    )


def format_completion_confirmation_prompt(visible_screen: str) -> str:
    """Pure: the double-finish confirmation prompt."""
    return (
        f"{visible_screen}\n\n"
        "IMPORTANT: You previously indicated task_complete=true. "
        "If the task is truly done, respond with task_complete=true again to confirm. "
        "If you need to do more work, set task_complete=false and provide commands."
    )


def apply_nudge(
    output: str,
    signal: StallSignal,
    state: State,
) -> str:
    """Pure: prepend stall-nudge text to observation if applicable."""
    notice = format_nudge_for_observation(signal, state)
    return notice + output


def prepend_screen_hint(output: str) -> str:
    """Pure: if the terminal is inside a classifiable program, add a hint line."""
    screen_class = stall.classify_screen(output)
    hint = stall.hint_for(screen_class)
    if hint:
        return f"[HINT: {hint}]\n{output}"
    return output


def termination_reason(status: str) -> str:
    """Pure: map run status to the termination_reason string stored in SQLite."""
    if status == "succeeded":
        return "task_complete_confirmed"
    if status == "cancelled":
        return "keyboard_interrupt"
    if status == "failed":
        return "max_turns_or_failure"
    return "unknown"


def clamp_command_wait(
    cmd: ParsedCommand,
    blocking_max_seconds: float,
) -> float:
    """Pure: compute the effective poll budget for a single command."""
    duration = cmd.duration or blocking_max_seconds
    return min(duration, blocking_max_seconds)


def detect_stall_for_commands(
    state: State,
    output: str,
    commands: Sequence[ParsedCommand],
    config: Config,
) -> tuple[StallState, StallSignal]:
    """Pure: thin wrapper over stall.detect_stall for consistency of import."""
    return stall.detect_stall(state, output, commands, config)
