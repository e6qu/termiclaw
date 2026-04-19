"""Three-subagent summarization pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from termiclaw.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from termiclaw.models import StepRecord

_log = get_logger("summarizer")


def should_summarize(total_prompt_tokens: int, threshold: int) -> bool:
    """Check if summarization should be triggered."""
    return total_prompt_tokens >= threshold


def run_summarization(
    instruction: str,
    recent_steps_text: str,
    full_steps_text: str,
    visible_screen: str,
    query_fn: Callable[[str], str],
) -> tuple[str, str]:
    """Run the three-subagent summarization pipeline.

    Returns (summary, qa_context). No fallback: any exception propagates
    to the caller, which fails the run (principle #6).
    """
    summary_prompt = (
        "Summarize the following agent interaction comprehensively.\n"
        "Cover: major actions taken, important information discovered, "
        "challenging problems encountered, current status.\n\n"
        f"Task: {instruction}\n\n"
        f"Interaction history:\n{recent_steps_text}"
    )
    summary = query_fn(summary_prompt)
    _log.info("Summary generated", extra={"summary_chars": len(summary)})

    question_prompt = (
        "Given this task and summary, generate at least 5 questions "
        "about critical information that might be missing from the summary.\n\n"
        f"Task: {instruction}\n\n"
        f"Summary: {summary}\n\n"
        f"Current terminal screen: {visible_screen}"
    )
    questions = query_fn(question_prompt)
    _log.info("Questions generated")

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
