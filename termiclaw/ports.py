"""Ports: typed Protocols describing the agent's side-effect surface.

The imperative shell (`shell.apply`) takes a `Ports` bundle and
dispatches commands through it. Production code wires up the defaults
in `runtime.build_default_ports`. Tests wire in fakes from
`tests/unit/fakes/` so no `mock.patch` is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from termiclaw.errors import (
        PlannerError,
        SummarizationError,
    )
    from termiclaw.models import ParseResult, PlannerUsage, StepRecord
    from termiclaw.result import Result
    from termiclaw.state import State
    from termiclaw.summarize_worker import (
        SummarizationComplete,
        SummarizationJob,
    )


class ContainerPort(Protocol):
    """Docker + tmux surface used by the agent loop."""

    def is_session_alive(self, container_id: str, session: str) -> bool: ...

    def send_and_wait_idle(  # noqa: PLR0913 — mirrors upstream signature
        self,
        container_id: str,
        session: str,
        keystrokes: str,
        *,
        max_seconds: float,
        poll_interval: float,
        max_command_length: int,
    ) -> bool: ...

    def send_keys(
        self,
        container_id: str,
        session: str,
        keys: str,
        *,
        max_command_length: int,
    ) -> None: ...

    def capture_visible(self, container_id: str, session: str) -> str: ...

    def get_incremental_output(
        self,
        container_id: str,
        session: str,
        previous_buffer: str,
    ) -> tuple[str, str]: ...

    def tail_bytes(self, buffer: str, limit: int) -> str: ...

    def truncate_output(self, text: str, *, max_bytes: int) -> str: ...


class PlannerPort(Protocol):
    """Claude Code subprocess interface."""

    def query(  # noqa: PLR0913 — mirrors upstream signature
        self,
        prompt: str,
        *,
        timeout: int,
        retries: int,
        claude_session_id: str,
        first_call: bool,
        resume_parent: str | None,
        fork_session: bool,
    ) -> Result[str, PlannerError]: ...

    def build_prompt(
        self,
        instruction: str,
        observation: str,
        summary: str | None,
        qa_context: str | None,
    ) -> str: ...

    def parse_response(self, raw: str) -> Result[ParseResult, PlannerError]: ...

    def extract_usage(self, raw: str) -> PlannerUsage: ...


class PersistencePort(Protocol):
    """Trajectory JSONL + SQLite writes."""

    def append_step(self, run_dir: Path, step: StepRecord) -> None: ...

    def insert_step(  # noqa: PLR0913 — discrete usage fields
        self,
        run_id: str,
        step: StepRecord,
        *,
        step_index: int,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        planner_duration_ms: int,
    ) -> None: ...

    def insert_run(self, state: State) -> None: ...

    def update_run(  # noqa: PLR0913 — discrete usage fields
        self,
        state: State,
        *,
        finished_at: str,
        termination_reason: str,
        total_prompt_tokens: int,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cost_usd: float,
    ) -> None: ...

    def write_run_metadata(
        self,
        run_dir: Path,
        state: State,
        *,
        finished_at: str,
        termination_reason: str,
    ) -> None: ...

    def aggregate_usage(self, run_id: str) -> PlannerUsage: ...


class ArtifactsPort(Protocol):
    """State-dump markdown refresh."""

    def refresh(
        self,
        state: State,
        run_dir: Path,
        query_fn: Callable[[str], str],
    ) -> None: ...


class SummarizePort(Protocol):
    """Background three-subagent summarization wrapper."""

    def idle(self) -> bool: ...

    def poll(self) -> Result[SummarizationComplete, SummarizationError] | None: ...

    def submit(self, job: SummarizationJob) -> None: ...

    def shutdown(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Ports:
    """Side-effect surface bundle passed into `shell.apply`."""

    container: ContainerPort
    planner: PlannerPort
    persistence: PersistencePort
    artifacts: ArtifactsPort
    summarize: SummarizePort
