"""Tests for termiclaw.summarize_worker — background summarization wrapper."""

from __future__ import annotations

import time

import pytest

from termiclaw.errors import SummarizationError
from termiclaw.result import Err, Ok
from termiclaw.summarize_worker import (
    SummarizationJob,
    SummarizationWorker,
)


def _job() -> SummarizationJob:
    return SummarizationJob(
        instruction="do X",
        recent_text="r",
        full_text="f",
        visible_screen="v",
    )


def test_worker_idle_initially():
    worker = SummarizationWorker(query_fn=lambda _p: "x")
    assert worker.idle()
    assert worker.poll() is None
    worker.shutdown()


def test_worker_runs_pipeline_and_returns_ok():
    """The worker invokes the three-subagent pipeline sequentially."""
    calls: list[str] = []

    def fake_query(prompt: str) -> str:
        calls.append(prompt[:16])
        return f"answer-{len(calls)}"

    worker = SummarizationWorker(query_fn=fake_query)
    worker.submit(_job())
    # Wait for completion.
    deadline = time.time() + 2.0
    result = None
    while time.time() < deadline:
        result = worker.poll()
        if result is not None:
            break
        time.sleep(0.01)
    assert isinstance(result, Ok)
    assert result.value.summary == "answer-1"
    assert "Questions" in result.value.qa_context
    assert "Answers" in result.value.qa_context
    # After a terminal result, worker is idle again.
    assert worker.idle()
    worker.shutdown()


def test_worker_returns_err_on_exception():
    def boom(_prompt: str) -> str:
        msg = "kaboom"
        raise SummarizationError(msg)

    worker = SummarizationWorker(query_fn=boom)
    worker.submit(_job())
    deadline = time.time() + 2.0
    result = None
    while time.time() < deadline:
        result = worker.poll()
        if result is not None:
            break
        time.sleep(0.01)
    assert isinstance(result, Err)
    assert "kaboom" in str(result.error)
    assert worker.idle()
    worker.shutdown()


def test_worker_rejects_double_submit():
    def slow(_prompt: str) -> str:
        time.sleep(0.1)
        return "x"

    worker = SummarizationWorker(query_fn=slow)
    worker.submit(_job())
    with pytest.raises(SummarizationError):
        worker.submit(_job())
    worker.shutdown()


def test_worker_poll_returns_none_while_running():
    def slow(_prompt: str) -> str:
        time.sleep(0.1)
        return "x"

    worker = SummarizationWorker(query_fn=slow)
    worker.submit(_job())
    assert worker.poll() is None
    assert not worker.idle()
    worker.shutdown()
