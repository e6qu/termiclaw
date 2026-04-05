"""Structured JSONL logging to stderr and log file."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
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


def log_dir() -> Path:
    """Return the platform-appropriate log directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "termiclaw"
    return Path.home() / ".local" / "state" / "termiclaw" / "log"


def setup_logging(run_id: str, level: int = logging.INFO) -> None:
    """Configure root logger with JSON formatter on stderr and log file."""
    global _run_id  # noqa: PLW0603
    _run_id = run_id

    root = logging.getLogger("termiclaw")
    root.setLevel(level)

    if not root.handlers:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(JsonFormatter())
        root.addHandler(stderr_handler)

        try:
            log_path = log_dir()
            log_path.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(
                log_path / f"{run_id}.jsonl",
                encoding="utf-8",
            )
            file_handler.setFormatter(JsonFormatter())
            root.addHandler(file_handler)
        except OSError:
            pass  # non-critical — stderr logging still works


def get_logger(component: str) -> logging.Logger:
    """Return a logger for the given component name."""
    return logging.getLogger(f"termiclaw.{component}")
