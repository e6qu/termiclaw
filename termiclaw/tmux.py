"""tmux subprocess wrapper: provision, send-keys, capture-pane."""

from __future__ import annotations

import re
import subprocess

from termiclaw.logging import get_logger

_log = get_logger("tmux")

_SEND_KEYS_MAX_COMMAND_LENGTH = 200_000
_MAX_OUTPUT_BYTES = 10_000
_TRUNCATION_MARKER = "\n\n... [truncated] ...\n\n"
_TMUX_SPECIAL_KEY_RE = re.compile(
    r"^(C-[a-z]|M-[a-z]|F[0-9]{1,2}|Enter|Escape|Tab|BSpace|"
    r"Up|Down|Left|Right|Home|End|PageUp|PageDown|Space|DC|IC)$",
)


# --- Session lifecycle ---


def provision_session(
    session_name: str,
    *,
    width: int = 160,
    height: int = 40,
    history_limit: int = 10_000_000,
) -> None:
    """Create a new tmux session."""
    subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            "-x",
            str(width),
            "-y",
            str(height),
            "bash",
            "--login",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "tmux",
            "set-option",
            "-t",
            session_name,
            "history-limit",
            str(history_limit),
        ],
        check=True,
        capture_output=True,
    )
    _log.info("Provisioned tmux session", extra={"session": session_name})


def destroy_session(session_name: str) -> None:
    """Kill a tmux session."""
    subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        check=False,
        capture_output=True,
    )
    _log.info("Destroyed tmux session", extra={"session": session_name})


def is_session_alive(session_name: str) -> bool:
    """Check if a tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def attach_session(session_name: str) -> None:
    """Attach to a tmux session (blocking)."""
    subprocess.run(
        ["tmux", "attach-session", "-t", session_name],
        check=False,
    )


# --- Keystroke operations ---


def send_keys(
    session_name: str,
    keys: str,
    *,
    max_command_length: int = _SEND_KEYS_MAX_COMMAND_LENGTH,
) -> None:
    """Send keystrokes to a tmux session, splitting if needed."""
    stripped = keys.strip()
    if _TMUX_SPECIAL_KEY_RE.match(stripped):
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, stripped],
            check=True,
            capture_output=True,
        )
    else:
        chunks = _split_keys(keys, max_command_length)
        for chunk in chunks:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "-l", chunk],
                check=True,
                capture_output=True,
            )


def _split_keys(keys: str, max_length: int) -> list[str]:
    """Split keys into chunks that fit within the OS argument size limit."""
    if len(keys.encode("utf-8")) <= max_length:
        return [keys]

    chunks: list[str] = []
    remaining = keys
    while remaining:
        chunk_size = _find_max_chunk_size(remaining, max_length)
        if chunk_size == 0:
            chunk_size = 1
        chunks.append(remaining[:chunk_size])
        remaining = remaining[chunk_size:]
    return chunks


def _find_max_chunk_size(text: str, max_length: int) -> int:
    """Binary search for the largest chunk that fits in max_length bytes."""
    low = 0
    high = len(text)
    result = 0
    while low <= high:
        mid = (low + high) // 2
        if len(text[:mid].encode("utf-8")) <= max_length:
            result = mid
            low = mid + 1
        else:
            high = mid - 1
    return result


# --- Capture operations ---


def capture_visible(session_name: str) -> str:
    """Capture the visible pane content."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", session_name],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


_CAPTURE_HISTORY_LINES = 10_000


def capture_full_history(session_name: str) -> str:
    """Capture recent scrollback history (last N lines)."""
    result = subprocess.run(
        [
            "tmux",
            "capture-pane",
            "-p",
            "-t",
            session_name,
            "-S",
            f"-{_CAPTURE_HISTORY_LINES}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def get_incremental_output(
    session_name: str,
    previous_buffer: str,
) -> tuple[str, str]:
    """Capture and diff output. Returns (formatted_output, new_buffer)."""
    current = capture_full_history(session_name)
    if previous_buffer and current.startswith(previous_buffer):
        incremental = current[len(previous_buffer) :]
        if incremental.strip():
            return (f"New Terminal Output:\n{incremental}", current)
    visible = capture_visible(session_name)
    return (f"Current Terminal Screen:\n{visible}", current)


# --- Output truncation ---


def truncate_output(text: str, *, max_bytes: int = _MAX_OUTPUT_BYTES) -> str:
    """Truncate output to approximately max_bytes, keeping first and last halves."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    # Use character-level slicing to avoid mid-codepoint splits
    marker_byte_len = len(_TRUNCATION_MARKER.encode("utf-8"))
    char_budget = max_bytes - marker_byte_len
    char_half = max(1, char_budget // 2)
    first = text[:char_half]
    last = text[-char_half:]
    return first + _TRUNCATION_MARKER + last
