"""Tests for termiclaw.summarizer."""

from termiclaw.models import ParsedCommand, StepRecord
from termiclaw.summarizer import (
    format_steps_text,
    run_fallback,
    run_short_summarization,
    run_summarization,
    should_summarize,
    summarize_with_fallback,
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


def test_run_short_summarization():
    def mock_query(prompt):
        return "short summary"

    summary, qa = run_short_summarization("task", "screen output", mock_query)
    assert summary == "short summary"
    assert qa == ""


def test_run_fallback_no_llm():
    summary, qa = run_fallback("fix bug", "terminal output here")
    assert "fix bug" in summary
    assert "terminal output here" in summary
    assert qa == ""


def test_summarize_with_fallback_success():
    def mock_query(_prompt):
        return "ok"

    summary, _qa = summarize_with_fallback("task", "recent", "full", "screen", mock_query)
    assert summary == "ok"


def test_summarize_with_fallback_full_fails():
    call_count = 0

    def mock_query(_prompt):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            msg = "fail on first call (inside full summarization)"
            raise RuntimeError(msg)
        return "short summary"

    summary, _qa = summarize_with_fallback("task", "recent", "full", "screen", mock_query)
    assert summary == "short summary"


def test_summarize_with_fallback_all_fail():
    def mock_query(_prompt):
        msg = "always fail"
        raise RuntimeError(msg)

    summary, _qa = summarize_with_fallback("task", "recent", "full", "screen", mock_query)
    assert "task" in summary
    assert _qa == ""


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
