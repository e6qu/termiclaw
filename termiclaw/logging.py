"""Structured JSONL logging to stderr."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import ClassVar


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for structured logging."""

    _BUILTIN_ATTRS: ClassVar[frozenset[str]] = frozenset(
        logging.LogRecord("", 0, "", 0, "", (), None).__dict__,
    )

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "component": record.name.removeprefix("termiclaw."),
            "run_id": _run_id,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._BUILTIN_ATTRS:
                entry[key] = value
        return json.dumps(entry, default=str)


_run_id: str = ""


def setup_logging(run_id: str, level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatter on stderr."""
    global _run_id  # noqa: PLW0603
    _run_id = run_id

    root = logging.getLogger("termiclaw")
    root.setLevel(level)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)


def get_logger(component: str) -> logging.Logger:
    """Return a logger for the given component name."""
    return logging.getLogger(f"termiclaw.{component}")
