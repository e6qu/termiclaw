"""Docker-hosted tmux substrate.

All session operations run inside a Docker container via `docker exec`.
Terminal-Bench-adjacent ubuntu-24-04 base image (see the repo's
Dockerfile). No host-tmux fallback; no modes.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from termiclaw.errors import ContainerProvisionError, ImageBuildError, SessionDeadError
from termiclaw.logging import get_logger
from termiclaw.result import Err, Ok

if TYPE_CHECKING:
    from termiclaw.result import Result

_log = get_logger("container")

_SEND_KEYS_MAX_COMMAND_LENGTH = 16_000
_MAX_OUTPUT_BYTES = 10_000
_TRUNCATION_MARKER = "\n\n... [truncated] ...\n\n"
SPECIAL_KEY_RE = re.compile(
    r"^(C-[a-z]|M-[a-z]|F[0-9]{1,2}|Enter|Escape|Tab|BSpace|"
    r"Up|Down|Left|Right|Home|End|PageUp|PageDown|Space|DC|IC)$",
)

_DOCKERFILE_PATH = Path(__file__).resolve().parent.parent / "Dockerfile"
_IMAGE_NAME_PREFIX = "termiclaw-base"


def _dockerfile_hash() -> str:
    """Return a 12-char sha256 prefix of the Dockerfile content."""
    content = _DOCKERFILE_PATH.read_bytes()
    return hashlib.sha256(content).hexdigest()[:12]


def image_tag() -> str:
    """Derive the image tag from the current Dockerfile's content hash."""
    return f"{_IMAGE_NAME_PREFIX}:{_dockerfile_hash()}"


def ensure_image() -> Result[str, ImageBuildError]:
    """Build the base image if not already present locally.

    Returns `Ok(tag)` on success, `Err(ImageBuildError)` on build failure.
    """
    tag = image_tag()
    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", tag],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        return Err(ImageBuildError("docker binary not found"))
    if inspect.returncode == 0:
        return Ok(tag)
    _log.info("Building Docker image", extra={"tag": tag})
    sys.stderr.write(f"Building {tag} (first-run only) ...\n")
    try:
        subprocess.run(
            [
                "docker",
                "build",
                "-t",
                tag,
                "-f",
                str(_DOCKERFILE_PATH),
                str(_DOCKERFILE_PATH.parent),
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return Err(ImageBuildError(f"docker build failed: exit {e.returncode}"))
    return Ok(tag)


def provision_container(image: str, network: str) -> Result[str, ContainerProvisionError]:
    """Start a container running `sleep infinity`; return its container ID."""
    name = f"termiclaw-{uuid.uuid4().hex[:8]}"
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "--network",
                network,
                image,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        return Err(ContainerProvisionError(f"docker run failed: {e.stderr or e}"))
    except FileNotFoundError:
        return Err(ContainerProvisionError("docker binary not found"))
    container_id = result.stdout.strip()
    _log.info(
        "Provisioned container",
        extra={"container_id": container_id, "container_name": name},
    )
    return Ok(container_id)


def destroy_container(container_id: str) -> None:
    """Stop the container (the `--rm` flag deletes it)."""
    subprocess.run(
        ["docker", "stop", container_id],
        check=False,
        capture_output=True,
    )
    _log.info("Destroyed container", extra={"container_id": container_id})


def _dx(container_id: str) -> list[str]:
    """Prefix for running a command inside the container."""
    return ["docker", "exec", container_id]


def provision_session(
    container_id: str,
    session_name: str,
    *,
    width: int = 160,
    height: int = 40,
    history_limit: int = 10_000_000,
) -> None:
    """Create a new tmux session inside the container."""
    subprocess.run(
        [
            *_dx(container_id),
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
            *_dx(container_id),
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
    _log.info(
        "Provisioned tmux session",
        extra={"session": session_name, "container_id": container_id},
    )


def is_session_alive(container_id: str, session_name: str) -> bool:
    """Check if a tmux session exists inside the container."""
    result = subprocess.run(
        [*_dx(container_id), "tmux", "has-session", "-t", session_name],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def attach(container_id: str, session_name: str) -> None:
    """Attach to the tmux session inside the container (blocking)."""
    subprocess.run(
        ["docker", "exec", "-it", container_id, "tmux", "attach-session", "-t", session_name],
        check=False,
    )


def send_keys(
    container_id: str,
    session_name: str,
    keys: str,
    *,
    max_command_length: int = _SEND_KEYS_MAX_COMMAND_LENGTH,
) -> None:
    """Send keystrokes to a tmux session inside the container.

    Dispatch (single rule, not a mode):
    - If `keys` is a single special key name (C-c, Enter, ...): send as-is.
    - Otherwise: shell-quote and let tmux parse embedded key names
      (`"ls -la Enter"` → types `ls -la` then presses Enter).
    """
    stripped = keys.strip()
    try:
        if SPECIAL_KEY_RE.match(stripped):
            subprocess.run(
                [*_dx(container_id), "tmux", "send-keys", "-t", session_name, stripped],
                check=True,
                capture_output=True,
            )
            return
        chunks = _split_keys(keys, max_command_length)
        for chunk in chunks:
            # No `shlex.quote` — subprocess list mode bypasses the shell, so
            # quoting would put literal single quotes *into* tmux's input
            # stream, which tmux would then type into the terminal (see
            # BUG-42; same class as BUG-15, which was never actually removed
            # from this call site).
            subprocess.run(
                [*_dx(container_id), "tmux", "send-keys", "-t", session_name, chunk],
                check=True,
                capture_output=True,
            )
    except subprocess.CalledProcessError as e:
        # docker exec / tmux failed — most commonly because the container
        # went away (rm'd) or the session died. Translate to the domain
        # error so `shell._apply_send_keys` catches it and emits
        # `SendKeysFailed` (→ run marked failed cleanly). See BUG-45.
        msg = f"send_keys failed: {e.stderr or e}"
        raise SessionDeadError(msg) from e


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


def capture_visible(container_id: str, session_name: str) -> str:
    """Capture the visible pane content."""
    try:
        result = subprocess.run(
            [*_dx(container_id), "tmux", "capture-pane", "-p", "-t", session_name],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        msg = f"capture_visible failed: {e.stderr or e}"
        raise SessionDeadError(msg) from e
    return result.stdout


def capture_full_history(container_id: str, session_name: str) -> str:
    """Capture the full scrollback history via `-S -`."""
    try:
        result = subprocess.run(
            [*_dx(container_id), "tmux", "capture-pane", "-p", "-t", session_name, "-S", "-"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        msg = f"capture_full_history failed: {e.stderr or e}"
        raise SessionDeadError(msg) from e
    return result.stdout


def send_and_wait_idle(  # noqa: PLR0913 — discrete timing knobs
    container_id: str,
    session_name: str,
    keys: str,
    *,
    max_seconds: float = 180.0,
    poll_interval: float = 0.5,
    max_command_length: int = _SEND_KEYS_MAX_COMMAND_LENGTH,
) -> bool:
    """Send keys followed by an echo marker; poll until the marker appears.

    Returns True if the marker was seen before `max_seconds` elapsed.

    Single-key special inputs (C-c, Enter, ...) cannot carry a marker,
    so they are sent via `send_keys` directly and this function returns
    immediately (no polling).
    """
    stripped = keys.strip()
    if SPECIAL_KEY_RE.match(stripped):
        send_keys(
            container_id,
            session_name,
            keys,
            max_command_length=max_command_length,
        )
        return True
    marker = f"TERMICLAW_DONE_{uuid.uuid4().hex[:8]}"
    augmented = f"{keys.rstrip()}; echo '{marker}'"
    send_keys(
        container_id,
        session_name,
        augmented,
        max_command_length=max_command_length,
    )
    send_keys(container_id, session_name, "Enter")
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        screen = capture_visible(container_id, session_name)
        if marker in screen:
            return True
        time.sleep(poll_interval)
    return False


def tail_bytes(text: str, n: int) -> str:
    """Return the last n utf-8-safe characters (approximately n bytes)."""
    if len(text) <= n:
        return text
    return text[-n:]


def get_incremental_output(
    container_id: str,
    session_name: str,
    previous_buffer: str,
) -> tuple[str, str]:
    """Capture and diff output.

    Three observation kinds (single path each, no fallbacks):
    - New Terminal Output: prior buffer is a prefix; return the suffix.
    - Current Terminal Screen: prior buffer matches exactly (no new output).
    - [TERMINAL RESET]: prefix-mismatch (clear/reset/resize).
    """
    current = capture_full_history(container_id, session_name)
    if previous_buffer and current.startswith(previous_buffer):
        incremental = current[len(previous_buffer) :]
        if incremental.strip():
            return (f"New Terminal Output:\n{incremental}", current)
        visible = capture_visible(container_id, session_name)
        return (f"Current Terminal Screen:\n{visible}", current)
    visible = capture_visible(container_id, session_name)
    if previous_buffer:
        return (f"[TERMINAL RESET]\n{visible}", current)
    return (f"Current Terminal Screen:\n{visible}", current)


def truncate_output(text: str, *, max_bytes: int = _MAX_OUTPUT_BYTES) -> str:
    """Truncate output to approximately max_bytes, keeping first and last halves."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    marker_byte_len = len(_TRUNCATION_MARKER.encode("utf-8"))
    char_budget = max_bytes - marker_byte_len
    char_half = max(1, char_budget // 2)
    first = text[:char_half]
    last = text[-char_half:]
    return first + _TRUNCATION_MARKER + last


def exec_in_container(container_id: str, cmd: str) -> str:
    """Run a shell command inside the container and return stdout."""
    result = subprocess.run(
        [*_dx(container_id), "bash", "-c", cmd],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def copy_in(container_id: str, src: Path, dst: str) -> None:
    """Copy a host path into the container: docker cp <src> <cid>:<dst>."""
    subprocess.run(
        ["docker", "cp", str(src), f"{container_id}:{dst}"],
        check=True,
        capture_output=True,
    )


def copy_out(container_id: str, src: str, dst: Path) -> None:
    """Copy a container path to the host: docker cp <cid>:<src> <dst>."""
    subprocess.run(
        ["docker", "cp", f"{container_id}:{src}", str(dst)],
        check=True,
        capture_output=True,
    )
