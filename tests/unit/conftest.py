"""Shared fixtures.

Tests do not stub internals. Production code exposes real injection
seams (env vars, constructor params, argv) — fixtures here use those
seams directly.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _skip_update_check() -> Iterator[None]:
    """Disable the background git ls-remote call for every unit test."""
    previous = os.environ.get("TERMICLAW_SKIP_UPDATE_CHECK")
    os.environ["TERMICLAW_SKIP_UPDATE_CHECK"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TERMICLAW_SKIP_UPDATE_CHECK", None)
        else:
            os.environ["TERMICLAW_SKIP_UPDATE_CHECK"] = previous


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Iterator[Path]:
    """Redirect `db.get_db_path()` at runtime via env var.

    Tests that invoke any `db.*` helper or CLI subcommand touching SQLite
    should take this fixture; the env var is cleared on teardown.
    """
    path = tmp_path / "termiclaw.db"
    previous = os.environ.get("TERMICLAW_DB_PATH")
    os.environ["TERMICLAW_DB_PATH"] = str(path)
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop("TERMICLAW_DB_PATH", None)
        else:
            os.environ["TERMICLAW_DB_PATH"] = previous
