"""Background summarization worker.

Summarization makes three sequential `claude -p` calls; each can take up
to five minutes. Running it inline blocks the agent's observation loop,
so stall detection goes dark and the tmux session is never nudged while
the model is busy summarizing.

This worker runs the pipeline on a single background thread. The agent
loop polls once per iteration: if the previous job finished, the result
is applied to state; otherwise the loop keeps running. Only one job is
allowed in flight at a time.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from termiclaw import summarizer
from termiclaw.errors import SummarizationError
from termiclaw.logging import get_logger
from termiclaw.result import Err, Ok

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from termiclaw.result import Result

_log = get_logger("summarize_worker")


@dataclass(frozen=True, slots=True)
class SummarizationJob:
    """Pending summarization work submitted to the worker."""

    instruction: str
    recent_text: str
    full_text: str
    visible_screen: str


@dataclass(frozen=True, slots=True)
class SummarizationComplete:
    """Successful summarization output."""

    summary: str
    qa_context: str


class SummarizationWorker:
    """Single-threaded background wrapper around `summarizer.run_summarization`."""

    def __init__(self, query_fn: Callable[[str], str]) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="summarize")
        self._query_fn = query_fn
        self._future: Future[SummarizationComplete] | None = None

    def idle(self) -> bool:
        """True iff no job is currently in flight."""
        return self._future is None

    def submit(self, job: SummarizationJob) -> None:
        """Start a summarization job in the background."""
        if self._future is not None:
            msg = "summarization already in flight"
            raise SummarizationError(msg)
        _log.info("submitting summarization job")
        self._future = self._executor.submit(self._run, job)

    def poll(self) -> Result[SummarizationComplete, SummarizationError] | None:
        """Return the completed result, None if still running.

        Once a terminal result is returned the worker clears its handle,
        so a subsequent `submit()` is allowed.
        """
        if self._future is None:
            return None
        if not self._future.done():
            return None
        future = self._future
        self._future = None
        exc = future.exception()
        if exc is not None:
            _log.exception("summarization worker raised", exc_info=exc)
            if isinstance(exc, SummarizationError):
                return Err(exc)
            return Err(SummarizationError(str(exc)))
        return Ok(future.result())

    def shutdown(self) -> None:
        """Stop the executor (called when the agent loop terminates)."""
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._future = None

    def _run(self, job: SummarizationJob) -> SummarizationComplete:
        summary, qa = summarizer.run_summarization(
            job.instruction,
            job.recent_text,
            job.full_text,
            job.visible_screen,
            self._query_fn,
        )
        return SummarizationComplete(summary=summary, qa_context=qa)
