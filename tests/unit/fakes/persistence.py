"""In-memory `PersistencePort` fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from termiclaw.models import PlannerUsage

if TYPE_CHECKING:
    from pathlib import Path

    from termiclaw.models import StepRecord
    from termiclaw.state import State


@dataclass(slots=True)
class _LoggedStep:
    run_id: str
    step: StepRecord
    step_index: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    planner_duration_ms: int


@dataclass
class FakePersistencePort:
    """Records every call for assertion. No real I/O."""

    appended: list[tuple[Path, StepRecord]] = field(default_factory=list)
    inserted_steps: list[_LoggedStep] = field(default_factory=list)
    inserted_runs: list[State] = field(default_factory=list)
    updated_runs: list[tuple[State, str, str]] = field(default_factory=list)
    written_metadata: list[tuple[Path, State, str, str]] = field(default_factory=list)
    usage: PlannerUsage | None = None

    def append_step(self, run_dir: Path, step: StepRecord) -> None:
        self.appended.append((run_dir, step))

    def insert_step(  # noqa: PLR0913
        self,
        run_id: str,
        step: StepRecord,
        *,
        step_index: int,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        planner_duration_ms: int,
    ) -> None:
        self.inserted_steps.append(
            _LoggedStep(
                run_id=run_id,
                step=step,
                step_index=step_index,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                planner_duration_ms=planner_duration_ms,
            ),
        )

    def insert_run(self, state: State) -> None:
        self.inserted_runs.append(state)

    def update_run(  # noqa: PLR0913
        self,
        state: State,
        *,
        finished_at: str,
        termination_reason: str,
        total_prompt_tokens: int,
        total_input_tokens: int,
        total_output_tokens: int,
        total_cost_usd: float,
    ) -> None:
        _ = (total_prompt_tokens, total_input_tokens, total_output_tokens, total_cost_usd)
        self.updated_runs.append((state, finished_at, termination_reason))

    def write_run_metadata(
        self,
        run_dir: Path,
        state: State,
        *,
        finished_at: str,
        termination_reason: str,
    ) -> None:
        self.written_metadata.append((run_dir, state, finished_at, termination_reason))

    def aggregate_usage(self, run_id: str) -> PlannerUsage:
        _ = run_id
        if self.usage is not None:
            return self.usage
        return PlannerUsage()
