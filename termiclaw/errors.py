"""Custom exception hierarchy.

Exceptions are programmer-error escape hatches. Expected failures flow
through `Result[T, E]` (see `termiclaw.result`). Any exception except
these five families or stdlib basics (KeyboardInterrupt, FileNotFoundError,
OSError) is a bug.
"""

from __future__ import annotations


class TermiclawError(Exception):
    """Base for all domain errors carried as `Err(TermiclawError(...))`."""


class ParseError(TermiclawError):
    """A JSON envelope or planner body failed validation."""

    def __init__(self, field: str, reason: str, raw: str) -> None:
        super().__init__(f"ParseError at `{field}`: {reason}")
        self.field = field
        self.reason = reason
        self.raw = raw


class PlannerError(TermiclawError):
    """claude -p subprocess failed in some way."""


class PlannerSubprocessError(PlannerError):
    """Non-zero exit code from claude -p."""

    def __init__(self, exit_code: int, stderr: str) -> None:
        super().__init__(f"claude -p exited {exit_code}: {stderr[:500]}")
        self.exit_code = exit_code
        self.stderr = stderr


class PlannerTimeoutError(PlannerError):
    """claude -p exceeded the configured timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"claude -p exceeded {timeout}s timeout")
        self.timeout = timeout


class ContainerError(TermiclawError):
    """Docker / container-level failure."""


class ImageBuildError(ContainerError):
    """`docker build` returned non-zero."""


class ContainerProvisionError(ContainerError):
    """`docker run` or session provision inside the container failed."""


class SessionDeadError(ContainerError):
    """tmux session inside the container is no longer alive."""


class DatabaseError(TermiclawError):
    """SQLite operation failed."""


class SummarizationError(TermiclawError):
    """Three-subagent summarization pipeline failed."""


class ArtifactRefreshError(TermiclawError):
    """State-dump artifact refresh failed."""
