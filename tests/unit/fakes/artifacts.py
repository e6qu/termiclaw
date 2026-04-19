"""In-memory `ArtifactsPort` fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from termiclaw.state import State


@dataclass
class FakeArtifactsPort:
    """Records refresh calls; optionally raises `refresh_raises`."""

    refresh_raises: Exception | None = None
    calls: list[tuple[State, Path]] = field(default_factory=list)

    def refresh(
        self,
        state: State,
        run_dir: Path,
        query_fn: Callable[[str], str],
    ) -> None:
        _ = query_fn
        if self.refresh_raises is not None:
            raise self.refresh_raises
        self.calls.append((state, run_dir))
