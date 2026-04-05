"""Data model. All stdlib dataclasses, no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedCommand:
    """A single command to send to the terminal."""

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


@dataclass
class RunState:
    """Mutable state for a single run."""

    run_id: str
    instruction: str
    tmux_session: str
    started_at: str
    status: str
    current_step: int = 0
    max_turns: int = 1_000_000
    pending_completion: bool = False
    previous_buffer: str = ""
    summary: str | None = None
    qa_context: str | None = None
    total_prompt_chars: int = 0
    recent_steps: list[StepRecord] = field(default_factory=list)


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
    max_duration: float = 60.0
    min_delay: float = 0.1
    planner_timeout: int = 300
    planner_retries: int = 3
    summarization_threshold: int = 100_000
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
    prompt_chars: int
    duration: str
