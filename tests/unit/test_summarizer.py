"""Tests for termiclaw.summarizer."""

import pytest

from termiclaw.models import ParsedCommand, StepRecord
from termiclaw.summarizer import (
    format_steps_text,
    run_summarization,
    should_summarize,
)


def test_should_summarize_below_threshold():
    assert should_summarize(50_000, 100_000) is False


def test_should_summarize_above_threshold():
    assert should_summarize(100_000, 100_000) is True


def test_should_summarize_at_threshold():
    assert should_summarize(100_000, 100_000) is True


def test_run_summarization_three_calls():
    calls = []

    def mock_query(prompt):
        calls.append(prompt)
        return f"response {len(calls)}"

    summary, qa = run_summarization("fix bug", "recent", "full", "screen", mock_query)
    assert len(calls) == 3
    assert "fix bug" in calls[0]
    assert summary == "response 1"
    assert "Questions:" in qa
    assert "Answers:" in qa


def test_run_summarization_returns_summary_and_qa():
    def mock_query(prompt):
        if "Summarize" in prompt:
            return "summary text"
        if "generate at least 5 questions" in prompt:
            return "Q1: what happened?"
        return "A1: things happened"

    summary, qa = run_summarization("task", "recent", "full", "screen", mock_query)
    assert summary == "summary text"
    assert "Q1" in qa
    assert "A1" in qa


def test_run_summarization_propagates_failure():
    """Principle #6: no fallback chain. Any failure propagates."""

    def mock_query(_prompt):
        msg = "planner failed"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="planner failed"):
        run_summarization("task", "recent", "full", "screen", mock_query)


def test_format_steps_text():
    cmd = ParsedCommand(keystrokes="ls\n", duration=0.5)
    steps = [
        StepRecord(
            step_id="s1",
            timestamp="t",
            source="agent",
            observation="file listing",
            analysis="checking files",
            commands=(cmd,),
        ),
        StepRecord(
            step_id="s2",
            timestamp="t",
            source="agent",
            observation="done",
            error="parse error",
        ),
    ]
    text = format_steps_text(steps)
    assert "s1" in text
    assert "checking files" in text
    assert "ls" in text
    assert "parse error" in text


def test_format_steps_text_empty():
    assert format_steps_text([]) == ""
