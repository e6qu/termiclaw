"""Default `Ports` implementations — thin facades over production modules.

Each port class wraps one module (`container`, `planner`, `trajectory`+
`db`, `artifacts`, `summarize_worker`) with the Protocol surface from
`ports.py`. `build_default_ports(config)` constructs the full bundle
that `agent.run()` injects into `shell.apply`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from termiclaw import artifacts as _artifacts_mod
from termiclaw import container as _container_mod
from termiclaw import db as _db_mod
from termiclaw import planner as _planner_mod
from termiclaw import trajectory as _trajectory_mod
from termiclaw.errors import PlannerError
from termiclaw.models import PlannerUsage
from termiclaw.ports import (
    ArtifactsPort,
    ContainerPort,
    PersistencePort,
    PlannerPort,
    Ports,
    SummarizePort,
)
from termiclaw.result import Err, Ok
from termiclaw.summarize_worker import SummarizationWorker

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from termiclaw.errors import (
        ContainerProvisionError,
        ImageBuildError,
        SummarizationError,
    )
    from termiclaw.models import Config, ParseResult, StepRecord
    from termiclaw.result import Result
    from termiclaw.state import State
    from termiclaw.summarize_worker import (
        SummarizationComplete,
        SummarizationJob,
    )

_POST_PROVISION_SESSION_WAIT_S = 0.5


class DefaultContainerPort(ContainerPort):
    """Facade over `termiclaw.container`."""

    def ensure_image(self) -> Result[str, ImageBuildError]:
        return _container_mod.ensure_image()

    def provision_container(
        self,
        image: str,
        network: str,
    ) -> Result[str, ContainerProvisionError]:
        return _container_mod.provision_container(image, network)

    def provision_session(
        self,
        container_id: str,
        session_name: str,
        *,
        width: int,
        height: int,
        history_limit: int,
    ) -> None:
        _container_mod.provision_session(
            container_id,
            session_name,
            width=width,
            height=height,
            history_limit=history_limit,
        )
        # Give tmux a moment to finish attaching the session before the
        # first send-keys / capture. Moved from agent.run() so tests
        # using FakeContainerPort don't need to patch time.sleep.
        time.sleep(_POST_PROVISION_SESSION_WAIT_S)

    def destroy_container(self, container_id: str) -> None:
        _container_mod.destroy_container(container_id)

    def is_session_alive(self, container_id: str, session: str) -> bool:
        return _container_mod.is_session_alive(container_id, session)

    def send_and_wait_idle(  # noqa: PLR0913
        self,
        container_id: str,
        session: str,
        keystrokes: str,
        *,
        max_seconds: float,
        poll_interval: float,
        max_command_length: int,
    ) -> bool:
        return _container_mod.send_and_wait_idle(
            container_id,
            session,
            keystrokes,
            max_seconds=max_seconds,
            poll_interval=poll_interval,
            max_command_length=max_command_length,
        )

    def send_keys(
        self,
        container_id: str,
        session: str,
        keys: str,
        *,
        max_command_length: int,
    ) -> None:
        _container_mod.send_keys(
            container_id,
            session,
            keys,
            max_command_length=max_command_length,
        )

    def capture_visible(self, container_id: str, session: str) -> str:
        return _container_mod.capture_visible(container_id, session)

    def get_incremental_output(
        self,
        container_id: str,
        session: str,
        previous_buffer: str,
    ) -> tuple[str, str]:
        return _container_mod.get_incremental_output(
            container_id,
            session,
            previous_buffer,
        )

    def tail_bytes(self, buffer: str, limit: int) -> str:
        return _container_mod.tail_bytes(buffer, limit)

    def truncate_output(self, text: str, *, max_bytes: int) -> str:
        return _container_mod.truncate_output(text, max_bytes=max_bytes)


class DefaultPlannerPort(PlannerPort):
    """Facade over `termiclaw.planner`."""

    def query(  # noqa: PLR0913
        self,
        prompt: str,
        *,
        timeout: int,
        retries: int,
        claude_session_id: str,
        first_call: bool,
        resume_parent: str | None,
        fork_session: bool,
    ) -> Result[str, PlannerError]:
        return _planner_mod.query_planner(
            prompt,
            timeout=timeout,
            retries=retries,
            claude_session_id=claude_session_id,
            first_call=first_call,
            resume_parent=resume_parent,
            fork_session=fork_session,
        )

    def build_prompt(
        self,
        instruction: str,
        observation: str,
        summary: str | None,
        qa_context: str | None,
    ) -> str:
        return _planner_mod.build_prompt(instruction, observation, summary, qa_context)

    def parse_response(self, raw: str) -> Result[ParseResult, PlannerError]:
        parsed = _planner_mod.parse_response(raw)
        if isinstance(parsed, Err):
            return Err(PlannerError(str(parsed.error)))
        return Ok(parsed.value)

    def extract_usage(self, raw: str) -> PlannerUsage:
        return _planner_mod.extract_usage(raw)


class DefaultPersistencePort(PersistencePort):
    """Facade over `termiclaw.trajectory` and `termiclaw.db`.

    Holds a single long-lived SQLite connection for the run. The
    connection is closed in `close()` when the shell tears down.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append_step(self, run_dir: Path, step: StepRecord) -> None:
        _trajectory_mod.append_step(run_dir, step)

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
        _db_mod.insert_step(
            self._conn,
            run_id,
            step,
            step_index=step_index,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            planner_duration_ms=planner_duration_ms,
        )

    def insert_run(self, state: State) -> None:
        _db_mod.insert_run(self._conn, state)

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
        _db_mod.update_run(
            self._conn,
            state,
            finished_at=finished_at,
            termination_reason=termination_reason,
            total_prompt_tokens=total_prompt_tokens,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_cost_usd=total_cost_usd,
        )

    def write_run_metadata(
        self,
        run_dir: Path,
        state: State,
        *,
        finished_at: str,
        termination_reason: str,
    ) -> None:
        _trajectory_mod.write_run_metadata(
            run_dir,
            state,
            finished_at=finished_at,
            termination_reason=termination_reason,
        )

    def aggregate_usage(self, run_id: str) -> PlannerUsage:
        cursor = self._conn.execute(
            "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
            "COALESCE(SUM(cost_usd),0.0) FROM steps WHERE run_id=?",
            (run_id,),
        )
        row = cursor.fetchone()
        if not row:
            return PlannerUsage()
        return PlannerUsage(input_tokens=row[0], output_tokens=row[1], cost_usd=row[2])

    def close(self) -> None:
        self._conn.close()


class DefaultArtifactsPort(ArtifactsPort):
    """Facade over `termiclaw.artifacts`.

    Wraps the config that `refresh_artifacts` needs. Reusing the port's
    constructor config avoids threading it through every call site.
    """

    def __init__(self, config: Config, visible_getter: Callable[[State], str]) -> None:
        self._config = config
        self._visible_getter = visible_getter

    def refresh(
        self,
        state: State,
        run_dir: Path,
        query_fn: Callable[[str], str],
    ) -> None:
        visible = self._visible_getter(state)
        _artifacts_mod.refresh_artifacts(
            state,
            run_dir,
            self._config,
            visible,
            query_fn,
        )


class DefaultSummarizePort(SummarizePort):
    """Facade over `termiclaw.summarize_worker.SummarizationWorker`."""

    def __init__(self, worker: SummarizationWorker) -> None:
        self._worker = worker

    def idle(self) -> bool:
        return self._worker.idle()

    def poll(self) -> Result[SummarizationComplete, SummarizationError] | None:
        return self._worker.poll()

    def submit(self, job: SummarizationJob) -> None:
        self._worker.submit(job)

    def shutdown(self) -> None:
        self._worker.shutdown()


def build_default_ports(
    config: Config,
    conn: sqlite3.Connection,
    summarize_query_fn: Callable[[str], str],
) -> Ports:
    """Wire up the production Ports bundle.

    `conn` is the per-run SQLite connection (owned by the shell).
    `summarize_query_fn` is the closure that calls the planner for
    each of the three summarization subagent prompts.
    """
    persistence = DefaultPersistencePort(conn)
    container_port = DefaultContainerPort()

    def _visible(state: State) -> str:
        return container_port.capture_visible(state.container_id, state.tmux_session)

    return Ports(
        container=container_port,
        planner=DefaultPlannerPort(),
        persistence=persistence,
        artifacts=DefaultArtifactsPort(config, _visible),
        summarize=DefaultSummarizePort(SummarizationWorker(summarize_query_fn)),
    )


__all__ = [
    "DefaultArtifactsPort",
    "DefaultContainerPort",
    "DefaultPersistencePort",
    "DefaultPlannerPort",
    "DefaultSummarizePort",
    "build_default_ports",
]
