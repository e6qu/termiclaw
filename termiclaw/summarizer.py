"""Three-subagent summarization pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from termiclaw.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from termiclaw.models import StepRecord

_log = get_logger("summarizer")

_FALLBACK_SCREEN_CHARS = 1000


def should_summarize(total_prompt_chars: int, threshold: int) -> bool:
    """Check if summarization should be triggered."""
    return total_prompt_chars >= threshold


def run_summarization(
    instruction: str,
    recent_steps_text: str,
    full_steps_text: str,
    visible_screen: str,
    query_fn: Callable[[str], str],
) -> tuple[str, str]:
    """Run the three-subagent summarization pipeline.

    Returns (summary, qa_context).
    """
    # Subagent 1: summary generation
    summary_prompt = (
        "Summarize the following agent interaction comprehensively.\n"
        "Cover: major actions taken, important information discovered, "
        "challenging problems encountered, current status.\n\n"
        f"Task: {instruction}\n\n"
        f"Interaction history:\n{recent_steps_text}"
    )
    summary = query_fn(summary_prompt)
    _log.info("Summary generated", extra={"summary_chars": len(summary)})

    # Subagent 2: question asking
    question_prompt = (
        "Given this task and summary, generate at least 5 questions "
        "about critical information that might be missing from the summary.\n\n"
        f"Task: {instruction}\n\n"
        f"Summary: {summary}\n\n"
        f"Current terminal screen: {visible_screen}"
    )
    questions = query_fn(question_prompt)
    _log.info("Questions generated")

    # Subagent 3: answer providing
    answer_prompt = (
        "Answer each of these questions in detail based on the "
        "interaction history.\n\n"
        f"Questions: {questions}\n\n"
        f"Interaction history:\n{full_steps_text}\n\n"
        f"Summary: {summary}"
    )
    answers = query_fn(answer_prompt)
    _log.info("Answers generated")

    qa_context = f"Questions:\n{questions}\n\nAnswers:\n{answers}"
    return (summary, qa_context)


def run_short_summarization(
    instruction: str,
    visible_screen: str,
    query_fn: Callable[[str], str],
) -> tuple[str, str]:
    """Single-call short summary fallback."""
    screen_tail = visible_screen[-_FALLBACK_SCREEN_CHARS:]
    prompt = (
        "Provide a brief summary of the current state of this task.\n\n"
        f"Task: {instruction}\n\n"
        f"Current terminal (last {_FALLBACK_SCREEN_CHARS} chars):\n{screen_tail}"
    )
    summary = query_fn(prompt)
    return (summary, "")


def run_fallback(instruction: str, visible_screen: str) -> tuple[str, str]:
    """Ultimate fallback with no LLM call."""
    screen_tail = visible_screen[-_FALLBACK_SCREEN_CHARS:]
    summary = f"Task: {instruction}\n\nLatest terminal output:\n{screen_tail}"
    return (summary, "")


def summarize_with_fallback(
    instruction: str,
    recent_steps_text: str,
    full_steps_text: str,
    visible_screen: str,
    query_fn: Callable[[str], str],
) -> tuple[str, str]:
    """Try full summarization, fall back to short, then ultimate."""
    try:
        return run_summarization(
            instruction,
            recent_steps_text,
            full_steps_text,
            visible_screen,
            query_fn,
        )
    except Exception:  # noqa: BLE001
        _log.warning("Full summarization failed, trying short")

    try:
        return run_short_summarization(instruction, visible_screen, query_fn)
    except Exception:  # noqa: BLE001
        _log.warning("Short summarization failed, using fallback")

    return run_fallback(instruction, visible_screen)


def format_steps_text(steps: Sequence[StepRecord]) -> str:
    """Format step records into readable text for summarization prompts."""
    parts: list[str] = []
    for step in steps:
        header = f"[Step {step.step_id[:8]}]"
        if step.analysis:
            header += f" Analysis: {step.analysis}"
        lines = [header]
        for cmd in step.commands:
            lines.append(f"  Command: {cmd.keystrokes!r} (wait {cmd.duration}s)")
        if step.observation:
            obs = step.observation
            for prefix in ("New Terminal Output:\n", "Current Terminal Screen:\n"):
                if obs.startswith(prefix):
                    obs = obs[len(prefix) :]
                    break
            lines.append(f"  Output: {obs[:200]}")
        if step.error:
            lines.append(f"  Error: {step.error}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
