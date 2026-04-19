"""State-dump artifacts: WHAT_WE_DID.md / STATUS.md / DO_NEXT.md / PLAN.md per run.

Written atomically (tmp + os.replace) so concurrent readers never see a
half-written file. Artifacts live at
`<runs_dir>/<run_id>/<state_dump_dir_name>/` — never at the repo root.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from termiclaw.logging import get_logger
from termiclaw.summarizer import format_steps_text

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from termiclaw.models import Config
    from termiclaw.state import State

_log = get_logger("artifacts")


_ARTIFACT_FILES: tuple[tuple[str, str], ...] = (
    ("what_we_did", "WHAT_WE_DID.md"),
    ("status", "STATUS.md"),
    ("do_next", "DO_NEXT.md"),
    ("plan", "PLAN.md"),
)


def artifacts_dir(run_dir: Path, config: Config) -> Path:
    """Return the artifacts directory for a run (creating if needed)."""
    path = run_dir / config.state_dump_dir_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_existing(a_dir: Path) -> dict[str, str]:
    """Load current artifact contents (empty string if missing)."""
    result: dict[str, str] = {}
    for key, filename in _ARTIFACT_FILES:
        p = a_dir / filename
        result[key] = p.read_text(encoding="utf-8") if p.exists() else ""
    return result


def _write_atomic(path: Path, content: str) -> None:
    """Write content to path atomically via tmp + rename."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _build_prompt(state: State, existing: dict[str, str], visible_screen: str) -> str:
    """Build the artifact-refresh prompt, including existing artifacts as context."""
    recent_text = format_steps_text(state.recent_steps) or f"[{state.current_step} steps so far]"
    existing_block = "\n\n".join(
        f"### Current {filename}\n{existing.get(key, '') or '(empty)'}"
        for key, filename in _ARTIFACT_FILES
    )
    return (
        "You are consolidating the state of an autonomous terminal agent's run "
        "for handoff. Produce markdown content for four files. Keep each concise "
        "but complete.\n\n"
        f"Task: {state.instruction}\n\n"
        f"Recent interaction history:\n{recent_text}\n\n"
        f"Current terminal state:\n{visible_screen}\n\n"
        f"Existing artifacts (update these rather than regenerate from scratch):\n\n"
        f"{existing_block}\n\n"
        "Respond with a single JSON object:\n\n"
        '{"what_we_did": "# What We Did\\n\\n- ...", '
        '"status": "# Status\\n\\n...", '
        '"do_next": "# Do Next\\n\\n1. ...", '
        '"plan": "# Plan\\n\\n..."}'
    )


def _parse_artifact_response(raw: str) -> dict[str, str]:
    """Parse the model's JSON response into artifact strings."""
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        msg = "artifact response is not a JSON object"
        raise TypeError(msg)
    return {key: str(obj.get(key, "")) for key, _ in _ARTIFACT_FILES}


def refresh_artifacts(
    state: State,
    run_dir: Path,
    config: Config,
    visible_screen: str,
    query_fn: Callable[[str], str],
) -> None:
    """Invoke the planner to regenerate artifacts; write them atomically.

    `query_fn` is called with the prompt and must return the planner's
    raw `result` JSON string. On any failure the run fails — there is
    no fallback (per principle #6).
    """
    a_dir = artifacts_dir(run_dir, config)
    existing = read_existing(a_dir)
    prompt = _build_prompt(state, existing, visible_screen)
    raw = query_fn(prompt)
    artifacts = _parse_artifact_response(raw)

    limit = config.state_dump_max_chars_per_file
    for key, filename in _ARTIFACT_FILES:
        content = artifacts[key][:limit]
        _write_atomic(a_dir / filename, content)
    _log.info("Artifacts refreshed", extra={"dir": str(a_dir)})


def should_refresh(state: State, config: Config) -> str:
    """Return a non-empty trigger reason if artifacts should refresh now."""
    if state.current_step == 0:
        return ""  # not at start — the very first call has nothing to summarize
    if state.current_step % config.state_dump_interval_turns == 0:
        return "interval"
    if state.total_prompt_tokens >= config.state_dump_token_threshold:
        return "token_threshold"
    return ""
