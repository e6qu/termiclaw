"""Data model. All stdlib dataclasses, no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from termiclaw.verifier import VerifierSpec


@dataclass(frozen=True)
class ParsedCommand:
    """A single command to send to the terminal.

    Keystrokes are interpreted by tmux's native key-name parser: write
    literal text for characters and key names (`Enter`, `C-c`, `Escape`)
    for control keys. Do NOT use `\\n`; use `Enter` instead. Example:
    `"ls -la Enter"` types `ls -la` then presses Enter.

    Every command is echo-marker-blocked (see `container.send_and_wait_idle`);
    `duration` is the advisory max-wait in seconds, capped by
    `Config.blocking_max_seconds`.
    """

    keystrokes: str
    duration: float


@dataclass(frozen=True)
class ParseResult:
    """Parsed planner response."""

    analysis: str = ""
    plan: str = ""
    commands: tuple[ParsedCommand, ...] = ()
    task_complete: bool = False
    error: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class StepRecord:
    """Immutable record of a single step for trajectory logging."""

    step_id: str
    timestamp: str
    source: str
    observation: str
    analysis: str | None = None
    plan: str | None = None
    commands: tuple[ParsedCommand, ...] = ()
    task_complete: bool = False
    error: str | None = None
    metrics: tuple[tuple[str, int | float | str], ...] = ()
    is_copied_context: bool = False


@dataclass(frozen=True)
class Config:
    """Run configuration with Terminus-matching defaults."""

    instruction: str
    max_turns: int = 1_000_000
    pane_width: int = 160
    pane_height: int = 40
    history_limit: int = 10_000_000
    max_output_bytes: int = 10_000
    max_command_length: int = 16_000
    min_delay: float = 0.1
    planner_timeout: int = 300
    planner_retries: int = 3
    summarization_token_threshold: int = 25_000
    stall_nudge_after: int = 2
    stall_force_interrupt_after: int = 4
    max_forced_interrupts_per_run: int = 5
    prompt_version: str = "2"
    capture_max_bytes: int = 2_000_000
    capture_tail_bytes: int = 200_000
    blocking_max_seconds: float = 180.0
    blocking_poll_interval: float = 0.5
    state_dump_interval_turns: int = 10
    state_dump_token_threshold: int = 100_000
    state_dump_dir_name: str = "artifacts"
    state_dump_max_chars_per_file: int = 8_000
    docker_network: str = "bridge"
    verifier: VerifierSpec | None = None
    keep_session: bool = False
    verbose: bool = False
    runs_dir: str = "./termiclaw_runs"


@dataclass(frozen=True)
class RunInfo:
    """Summary of a completed run for listing."""

    run_id: str
    instruction: str
    status: str
    total_steps: int
    started_at: str
    finished_at: str
    tmux_session: str
    termination_reason: str
    prompt_tokens: int
    duration: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    parent_run_id: str | None = None
    claude_session_id: str = ""
    container_id: str = ""


@dataclass(frozen=True)
class PlannerUsage:
    """Token/cost metrics from a single claude -p call."""

    input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    claude_session_id: str = ""
