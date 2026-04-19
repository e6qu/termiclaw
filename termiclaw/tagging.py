"""Failure tagging: a closed set of categories for labelling failed runs.

Each category names a recurring failure mode observed during eval runs.
The CLI (`termiclaw tag ... --category <name>`) rejects anything outside
this set so the histogram stays meaningful across runs.
"""

from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    """Closed set of failure modes for tagged runs."""

    PREMATURE_COMPLETION = "premature_completion"
    PARSE_FAILURE = "parse_failure"
    WRONG_COMMAND = "wrong_command"
    STUCK_LOOP = "stuck_loop"
    TIMEOUT = "timeout"
    HALLUCINATION = "hallucination"
    CONTAINER_ERROR = "container_error"
    VERIFIER_FAILURE = "verifier_failure"


def valid_categories() -> tuple[str, ...]:
    """Return the full set of valid category strings, ordered for display."""
    return tuple(c.value for c in FailureCategory)


def is_valid_category(value: str) -> bool:
    """Return True if `value` is one of the known failure categories."""
    return value in {c.value for c in FailureCategory}
