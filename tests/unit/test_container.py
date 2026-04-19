"""Tests for termiclaw.container (mocked subprocess).

Container-specific: every tmux call must be prefixed with
`docker exec <cid>` and take `container_id` as the first arg.
"""

import subprocess
from unittest.mock import patch

from termiclaw.container import (
    _find_max_chunk_size,
    _split_keys,
    capture_full_history,
    capture_visible,
    get_incremental_output,
    is_session_alive,
    provision_session,
    send_and_wait_idle,
    send_keys,
    tail_bytes,
    truncate_output,
)

_CID = "testcontainer"


def test_split_keys_under_limit():
    chunks = _split_keys("ls -la\n", 16_000)
    assert chunks == ["ls -la\n"]


def test_split_keys_over_limit():
    big_text = "a" * 20_000
    chunks = _split_keys(big_text, 100)
    assert len(chunks) > 1
    assert "".join(chunks) == big_text


def test_split_keys_all_chunks_under_limit():
    big_text = "b" * 5000
    chunks = _split_keys(big_text, 200)
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= 200


def test_find_max_chunk_size_basic():
    size = _find_max_chunk_size("hello world", 100)
    assert size == len("hello world")


def test_find_max_chunk_size_tight():
    size = _find_max_chunk_size("a" * 1000, 10)
    assert size > 0
    assert size < 1000


def test_truncate_output_under_limit():
    assert truncate_output("short text") == "short text"


def test_truncate_output_over_limit():
    big_text = "x" * 20_000
    result = truncate_output(big_text, max_bytes=1000)
    assert len(result.encode("utf-8")) <= 1200  # some headroom for the marker
    assert "truncated" in result


def test_provision_session_argv():
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        provision_session(_CID, "s1", width=80, height=24, history_limit=1000)
    assert mock_run.call_count == 2
    new_session_args = mock_run.call_args_list[0][0][0]
    assert new_session_args[:3] == ["docker", "exec", _CID]
    assert "tmux" in new_session_args
    assert "new-session" in new_session_args


def test_is_session_alive_argv():
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        alive = is_session_alive(_CID, "s1")
    assert alive is True
    args = mock_run.call_args[0][0]
    assert args[:3] == ["docker", "exec", _CID]
    assert "has-session" in args


def test_capture_visible_argv():
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="screen",
        )
        result = capture_visible(_CID, "s1")
    assert result == "screen"
    args = mock_run.call_args[0][0]
    assert args[:3] == ["docker", "exec", _CID]


def test_capture_full_history_uses_full_scrollback():
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="hist",
        )
        result = capture_full_history(_CID, "s1")
    assert result == "hist"
    args = mock_run.call_args[0][0]
    assert args[:3] == ["docker", "exec", _CID]
    assert "-S" in args
    # Full scrollback: `-S -`
    idx = args.index("-S")
    assert args[idx + 1] == "-"


def test_get_incremental_output_new_output():
    with (
        patch("termiclaw.container.capture_full_history", return_value="old\nnew line\n"),
        patch("termiclaw.container.capture_visible", return_value="screen"),
    ):
        output, buffer = get_incremental_output(_CID, "s1", "old\n")
    assert output.startswith("New Terminal Output:\n")
    assert "new line" in output
    assert buffer == "old\nnew line\n"


def test_get_incremental_output_reset_detected():
    with (
        patch(
            "termiclaw.container.capture_full_history",
            return_value="completely different",
        ),
        patch("termiclaw.container.capture_visible", return_value="visible screen"),
    ):
        output, _buf = get_incremental_output(_CID, "s1", "old stuff")
    assert output.startswith("[TERMINAL RESET]\n")
    assert "visible screen" in output


def test_get_incremental_output_no_prior_buffer():
    with (
        patch("termiclaw.container.capture_full_history", return_value="new content"),
        patch("termiclaw.container.capture_visible", return_value="screen"),
    ):
        output, _buf = get_incremental_output(_CID, "s1", "")
    assert output.startswith("Current Terminal Screen:\n")


def test_get_incremental_output_no_change():
    with (
        patch("termiclaw.container.capture_full_history", return_value="same"),
        patch("termiclaw.container.capture_visible", return_value="screen"),
    ):
        output, _buf = get_incremental_output(_CID, "s1", "same")
    assert output.startswith("Current Terminal Screen:\n")


def test_tail_bytes_under_limit():
    assert tail_bytes("hello", 100) == "hello"


def test_tail_bytes_over_limit():
    assert tail_bytes("abcdefghij", 3) == "hij"


def test_send_keys_special_single_key():
    """Single tmux key name (C-c, Enter) goes through the no-quote path."""
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        send_keys(_CID, "s1", "C-c")
    args = mock_run.call_args[0][0]
    assert args[:3] == ["docker", "exec", _CID]
    assert "C-c" in args


def test_send_keys_text_passed_verbatim():
    """Non-special keystrokes reach tmux *unquoted* — `subprocess.run([...])`
    uses list mode (no shell), so `shlex.quote` would inject literal single
    quotes into tmux's input and break bash parsing (BUG-42/BUG-15).
    """
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        send_keys(_CID, "s1", "ls -la Enter")
    args = mock_run.call_args[0][0]
    assert args[:3] == ["docker", "exec", _CID]
    assert args[-1] == "ls -la Enter"
    assert "'ls -la Enter'" not in args


def test_send_keys_translates_calledprocesserror_to_sessiondead():
    """BUG-45: raw CalledProcessError from docker exec must become a
    ContainerError subclass (`SessionDeadError`) so shell's existing
    `except ContainerError:` catches it and the run fails cleanly
    rather than exploding with a traceback.
    """
    import pytest  # noqa: PLC0415 — local import keeps top-level imports tidy

    from termiclaw.errors import SessionDeadError  # noqa: PLC0415

    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(
            1,
            ["docker", "exec"],
            stderr=b"no such container\n",
        )
        with pytest.raises(SessionDeadError):
            send_keys(_CID, "s1", "ls -la\n")


def test_send_keys_single_quotes_not_escaped():
    """A payload containing single quotes must reach tmux literally — no
    `shlex.quote`'s `'\"'\"'` dance, which would type literal quotes into
    the terminal (see BUG-42).
    """
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        send_keys(_CID, "s1", "echo 'e2e ok' > /tmp/x.txt\n")
    args = mock_run.call_args[0][0]
    assert args[-1] == "echo 'e2e ok' > /tmp/x.txt\n"


def test_send_keys_special_keys_recognized():
    specials = ["Enter", "Escape", "Tab", "Up", "Down", "C-c", "C-d", "F12", "BSpace"]
    for key in specials:
        with patch("termiclaw.container.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            send_keys(_CID, "s1", key)
        args = mock_run.call_args[0][0]
        assert key in args, f"Key {key} should be sent as a special key name"


def test_send_keys_large_text_chunks():
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        big_text = "a" * 20_000
        send_keys(_CID, "s1", big_text, max_command_length=100)
    assert mock_run.call_count > 1


def test_send_and_wait_idle_special_returns_immediately():
    """Single special key cannot carry a marker; returns True without polling."""
    with patch("termiclaw.container.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        ok = send_and_wait_idle(_CID, "s1", "C-c")
    assert ok is True


def test_send_and_wait_idle_marker_seen():
    with (
        patch("termiclaw.container.subprocess.run") as mock_run,
        patch("termiclaw.container.capture_visible") as mock_cap,
        patch("termiclaw.container.time.sleep"),
        patch("termiclaw.container.uuid.uuid4") as mock_uuid,
    ):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        mock_uuid.return_value.hex = "abcd1234xx"
        mock_cap.side_effect = ["no marker", "done TERMICLAW_DONE_abcd1234 now"]
        ok = send_and_wait_idle(_CID, "s1", "make test", max_seconds=5, poll_interval=0.1)
    assert ok is True


def test_send_and_wait_idle_times_out():
    with (
        patch("termiclaw.container.subprocess.run") as mock_run,
        patch("termiclaw.container.capture_visible", return_value="no marker"),
        patch("termiclaw.container.time.sleep"),
        patch("termiclaw.container.time.monotonic") as mock_mono,
    ):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        mock_mono.side_effect = [0.0, 100.0]
        ok = send_and_wait_idle(_CID, "s1", "sleep 200", max_seconds=5, poll_interval=0.1)
    assert ok is False
