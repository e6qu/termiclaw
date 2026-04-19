"""In-memory `SummarizePort` fake."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from termiclaw.errors import SummarizationError
    from termiclaw.result import Result
    from termiclaw.summarize_worker import (
        SummarizationComplete,
        SummarizationJob,
    )


@dataclass
class FakeSummarizePort:
    """Deterministic summarize fake.

    - `idle_flag` controls `idle()`.
    - `poll_responses` is a deque that `poll()` drains; an empty deque
      returns None (busy / no result).
    - `submitted` records every `submit` call.
    - `shutdown_count` tracks shutdowns.
    """

    idle_flag: bool = True
    poll_responses: deque[Result[SummarizationComplete, SummarizationError] | None] = field(
        default_factory=deque,
    )
    submitted: list[SummarizationJob] = field(default_factory=list)
    shutdown_count: int = 0

    def idle(self) -> bool:
        return self.idle_flag

    def poll(self) -> Result[SummarizationComplete, SummarizationError] | None:
        if self.poll_responses:
            return self.poll_responses.popleft()
        return None

    def submit(self, job: SummarizationJob) -> None:
        self.submitted.append(job)
        self.idle_flag = False

    def shutdown(self) -> None:
        self.shutdown_count += 1
