"""In-memory `ContainerPort` fake."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from termiclaw.result import Ok

if TYPE_CHECKING:
    from collections.abc import Iterable

    from termiclaw.errors import (
        ContainerError,
        ContainerProvisionError,
        ImageBuildError,
    )
    from termiclaw.result import Result


@dataclass
class FakeContainerPort:
    """Container fake backed by scripted responses.

    - `incremental_outputs` is a deque of `(text, next_buffer)` pairs
      returned in order by `get_incremental_output`. Empty deque
      falls back to returning `("", previous_buffer)`.
    - `visible_screens` is a deque of strings for `capture_visible`.
    - `is_alive` toggles `is_session_alive`. Can be overridden via
      `alive_sequence` to cycle through booleans.
    - `send_and_wait_raises` / `send_keys_raises` will raise
      `ContainerError` when non-None.
    """

    is_alive: bool = True
    alive_sequence: deque[bool] = field(default_factory=deque)
    incremental_outputs: deque[tuple[str, str]] = field(default_factory=deque)
    visible_screens: deque[str] = field(default_factory=deque)
    send_and_wait_result: bool = True
    send_and_wait_raises: Exception | None = None
    send_keys_raises: Exception | None = None
    ensure_image_result: Result[str, ImageBuildError] | None = None
    provision_container_result: Result[str, ContainerProvisionError] | None = None
    provision_session_raises: Exception | None = None
    # observation logs for assertions
    sent_keys: list[tuple[str, int]] = field(default_factory=list)
    interrupts: list[str] = field(default_factory=list)
    destroyed_containers: list[str] = field(default_factory=list)

    def ensure_image(self) -> Result[str, ImageBuildError]:
        return (
            self.ensure_image_result if self.ensure_image_result is not None else Ok("fake-image")
        )

    def provision_container(
        self,
        image: str,
        network: str,
    ) -> Result[str, ContainerProvisionError]:
        _ = (image, network)
        return (
            self.provision_container_result
            if self.provision_container_result is not None
            else Ok("fake-cid")
        )

    def provision_session(
        self,
        container_id: str,
        session_name: str,
        *,
        width: int,
        height: int,
        history_limit: int,
    ) -> None:
        _ = (container_id, session_name, width, height, history_limit)
        if self.provision_session_raises is not None:
            raise self.provision_session_raises

    def destroy_container(self, container_id: str) -> None:
        self.destroyed_containers.append(container_id)

    def is_session_alive(self, container_id: str, session: str) -> bool:
        _ = (container_id, session)
        if self.alive_sequence:
            return self.alive_sequence.popleft()
        return self.is_alive

    def send_and_wait_idle(  # noqa: PLR0913
        self,
        container_id: str,
        session: str,
        keystrokes: str,
        *,
        max_seconds: float,
        poll_interval: float,
        max_command_length: int,
    ) -> bool:
        _ = (container_id, session, max_seconds, poll_interval)
        if self.send_and_wait_raises is not None:
            raise self.send_and_wait_raises
        self.sent_keys.append((keystrokes, max_command_length))
        return self.send_and_wait_result

    def send_keys(
        self,
        container_id: str,
        session: str,
        keys: str,
        *,
        max_command_length: int,
    ) -> None:
        _ = (container_id, session, max_command_length)
        if self.send_keys_raises is not None:
            raise self.send_keys_raises
        self.interrupts.append(keys)

    def capture_visible(self, container_id: str, session: str) -> str:
        _ = (container_id, session)
        if self.visible_screens:
            return self.visible_screens.popleft()
        return ""

    def get_incremental_output(
        self,
        container_id: str,
        session: str,
        previous_buffer: str,
    ) -> tuple[str, str]:
        _ = (container_id, session)
        if self.incremental_outputs:
            return self.incremental_outputs.popleft()
        return ("", previous_buffer)

    def tail_bytes(self, buffer: str, limit: int) -> str:
        return buffer[-limit:] if len(buffer) > limit else buffer

    def truncate_output(self, text: str, *, max_bytes: int) -> str:
        return text[:max_bytes]


def scripted(outputs: Iterable[tuple[str, str]]) -> FakeContainerPort:
    """Convenience constructor for a container with pre-scripted outputs."""
    port = FakeContainerPort()
    port.incremental_outputs.extend(outputs)
    return port


def raise_on_send(error: ContainerError) -> FakeContainerPort:
    """A container whose `send_and_wait_idle` raises `error`."""
    return FakeContainerPort(send_and_wait_raises=error)
