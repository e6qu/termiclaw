"""Integration tests for termiclaw.tmux against real tmux."""

import time
import uuid

import pytest

from termiclaw.tmux import (
    capture_full_history,
    capture_visible,
    destroy_session,
    get_incremental_output,
    is_session_alive,
    provision_session,
    send_keys,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def tmux_session():
    name = f"termiclaw-test-{uuid.uuid4().hex[:8]}"
    provision_session(name, width=80, height=24, history_limit=10_000)
    time.sleep(0.5)  # wait for shell to start
    yield name
    destroy_session(name)


def test_provision_and_destroy(tmux_session):
    assert is_session_alive(tmux_session) is True
    destroy_session(tmux_session)
    assert is_session_alive(tmux_session) is False


def test_send_keys_and_capture(tmux_session):
    send_keys(tmux_session, "echo hello_world\n")
    time.sleep(0.5)
    visible = capture_visible(tmux_session)
    assert "hello_world" in visible


def test_capture_visible_vs_full(tmux_session):
    send_keys(tmux_session, "echo test_line\n")
    time.sleep(0.5)
    visible = capture_visible(tmux_session)
    full = capture_full_history(tmux_session)
    assert "test_line" in visible
    assert "test_line" in full
    assert len(full) >= len(visible)


def test_incremental_output(tmux_session):
    send_keys(tmux_session, "echo first_cmd\n")
    time.sleep(0.5)
    _, buffer = get_incremental_output(tmux_session, "")

    send_keys(tmux_session, "echo second_cmd\n")
    time.sleep(0.5)
    output, _ = get_incremental_output(tmux_session, buffer)
    assert "second_cmd" in output
