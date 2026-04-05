"""Tests for termiclaw.tmux (mocked subprocess)."""

import subprocess
from unittest.mock import patch

from termiclaw.tmux import (
    _find_max_chunk_size,
    _split_keys,
    capture_full_history,
    capture_visible,
    get_incremental_output,
    is_session_alive,
    provision_session,
    send_keys,
    truncate_output,
)

# --- Key splitting ---


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


# --- Output truncation ---


def test_truncate_output_under_limit():
    text = "short text"
    assert truncate_output(text, max_bytes=100) == text


def test_truncate_output_over_limit():
    text = "x" * 20_000
    result = truncate_output(text, max_bytes=1000)
    assert len(result.encode()) <= 1000 + 100  # some overhead for marker
    assert "... [truncated] ..." in result


def test_truncate_output_preserves_ends():
    text = "START" + "x" * 20_000 + "END"
    result = truncate_output(text, max_bytes=1000)
    assert result.startswith("START")
    assert result.endswith("END")


def test_truncate_output_unicode():
    text = "\U0001f600" * 5000  # emoji, 4 bytes each
    result = truncate_output(text, max_bytes=1000)
    assert "... [truncated] ..." in result


def test_truncate_output_unicode_no_mojibake():
    text = "\U0001f600" * 5000
    result = truncate_output(text, max_bytes=1000)
    assert "\ufffd" not in result


# --- Incremental output ---


def test_get_incremental_output_new_content():
    with patch("termiclaw.tmux.capture_full_history", return_value="old\nnew line\n"):
        output, buffer = get_incremental_output("sess", "old\n")
    assert output.startswith("New Terminal Output:\n")
    assert "new line" in output
    assert buffer == "old\nnew line\n"


def test_get_incremental_output_no_match():
    with (
        patch("termiclaw.tmux.capture_full_history", return_value="completely different"),
        patch("termiclaw.tmux.capture_visible", return_value="visible screen"),
    ):
        output, _buffer = get_incremental_output("sess", "old stuff")
    assert output.startswith("Current Terminal Screen:\n")
    assert "visible screen" in output


def test_get_incremental_output_no_change():
    with (
        patch("termiclaw.tmux.capture_full_history", return_value="same"),
        patch("termiclaw.tmux.capture_visible", return_value="screen"),
    ):
        output, _buffer = get_incremental_output("sess", "same")
    assert output.startswith("Current Terminal Screen:\n")


def test_get_incremental_output_empty_previous():
    with (
        patch("termiclaw.tmux.capture_full_history", return_value="some output"),
        patch("termiclaw.tmux.capture_visible", return_value="visible"),
    ):
        output, buffer = get_incremental_output("sess", "")
    assert output.startswith("Current Terminal Screen:\n")
    assert buffer == "some output"


# --- Session operations (mocked) ---


def test_provision_session_commands():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        provision_session("test-sess", width=80, height=24, history_limit=1000)

    assert mock_run.call_count == 2
    new_session_call = mock_run.call_args_list[0]
    assert "new-session" in new_session_call[0][0]
    assert "test-sess" in new_session_call[0][0]


def test_is_session_alive_true():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        assert is_session_alive("sess") is True


def test_is_session_alive_false():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)
        assert is_session_alive("sess") is False


def test_send_keys_basic():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        send_keys("sess", "ls\n")
    mock_run.assert_called_once()
    cmd_list = mock_run.call_args[0][0]
    assert "send-keys" in cmd_list
    assert "-l" in cmd_list


def test_send_keys_special_key_no_l_flag():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        send_keys("sess", "Enter")
    cmd_list = mock_run.call_args[0][0]
    assert "-l" not in cmd_list
    assert "Enter" in cmd_list


def test_send_keys_ctrl_c_special():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        send_keys("sess", "C-c")
    cmd_list = mock_run.call_args[0][0]
    assert "-l" not in cmd_list
    assert "C-c" in cmd_list


def test_send_keys_special_keys_recognized():
    specials = [
        "Enter",
        "Escape",
        "Tab",
        "Up",
        "Down",
        "Left",
        "Right",
        "C-c",
        "C-d",
        "C-z",
        "M-a",
        "F1",
        "F12",
        "Space",
        "BSpace",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "DC",
        "IC",
    ]
    for key in specials:
        with patch("termiclaw.tmux.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            send_keys("sess", key)
        cmd_list = mock_run.call_args[0][0]
        assert "-l" not in cmd_list, f"Key {key} should be special (no -l flag)"


def test_send_keys_large_splits():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        big_text = "a" * 20_000
        send_keys("sess", big_text, max_command_length=100)
    assert mock_run.call_count > 1


def test_capture_visible_returns_stdout():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="visible output"
        )
        result = capture_visible("sess")
    assert result == "visible output"


def test_capture_full_history_returns_stdout():
    with patch("termiclaw.tmux.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="full history"
        )
        result = capture_full_history("sess")
    assert result == "full history"
