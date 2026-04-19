"""Integration tests: real Docker + real tmux inside a container.

Skipped automatically when Docker is not available (e.g. CI without docker).
"""

from __future__ import annotations

import subprocess
import time
import uuid

import pytest

from termiclaw.container import (
    capture_visible,
    destroy_container,
    ensure_image,
    get_incremental_output,
    is_session_alive,
    provision_container,
    provision_session,
    send_and_wait_idle,
    send_keys,
)
from termiclaw.result import Ok


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return True


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available"),
]


@pytest.fixture
def container_session():
    image_result = ensure_image()
    assert isinstance(image_result, Ok), f"image build failed: {image_result}"
    provision_result = provision_container(image_result.value, network="bridge")
    assert isinstance(provision_result, Ok), f"container provision failed: {provision_result}"
    container_id = provision_result.value
    session_name = f"termiclaw-test-{uuid.uuid4().hex[:8]}"
    try:
        provision_session(container_id, session_name)
        time.sleep(0.3)
        yield (container_id, session_name)
    finally:
        destroy_container(container_id)


def test_session_alive_after_provision(container_session):
    cid, sess = container_session
    assert is_session_alive(cid, sess) is True


def test_send_and_wait_idle_echo(container_session):
    cid, sess = container_session
    ok = send_and_wait_idle(cid, sess, "echo termiclaw-hello", max_seconds=10, poll_interval=0.1)
    assert ok is True
    visible = capture_visible(cid, sess)
    assert "termiclaw-hello" in visible


def test_send_keys_special(container_session):
    cid, sess = container_session
    send_and_wait_idle(cid, sess, "echo before-c-c", max_seconds=5, poll_interval=0.1)
    send_keys(cid, sess, "C-c")
    time.sleep(0.2)
    visible = capture_visible(cid, sess)
    assert "before-c-c" in visible


def test_get_incremental_output_after_echo(container_session):
    cid, sess = container_session
    _output, buffer = get_incremental_output(cid, sess, "")
    send_and_wait_idle(cid, sess, "echo incremental-test", max_seconds=5, poll_interval=0.1)
    output2, _buf = get_incremental_output(cid, sess, buffer)
    assert "incremental-test" in output2
