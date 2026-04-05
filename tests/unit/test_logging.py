"""Tests for termiclaw.logging."""

import json
import logging
from unittest.mock import patch

import termiclaw.logging as log_mod
from termiclaw.logging import JsonFormatter, get_logger, log_dir, setup_logging


def test_json_formatter_output():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="termiclaw.agent",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="step started",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["level"] == "INFO"
    assert parsed["component"] == "agent"
    assert parsed["msg"] == "step started"
    assert "ts" in parsed


def test_json_formatter_extra_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="termiclaw.planner",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="query sent",
        args=(),
        exc_info=None,
    )
    record.step = 3  # type: ignore[attr-defined]
    record.prompt_chars = 15000  # type: ignore[attr-defined]
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["step"] == 3
    assert parsed["prompt_chars"] == 15000


def test_json_formatter_single_line():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="termiclaw.tmux",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="multi\nline\nmessage",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    assert "\n" not in output
    parsed = json.loads(output)
    assert parsed["msg"] == "multi\nline\nmessage"


def test_json_formatter_component_stripping():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="termiclaw.summarizer",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["component"] == "summarizer"


def test_json_formatter_non_termiclaw_name():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="other.module",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="x",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["component"] == "other.module"


def test_setup_logging_adds_handler():
    logger = logging.getLogger("termiclaw")
    initial_count = len(logger.handlers)
    setup_logging("test-run-id", level=logging.DEBUG)
    assert len(logger.handlers) == initial_count + 1 or len(logger.handlers) >= 1
    assert logger.level == logging.DEBUG
    # Cleanup
    logger.handlers.clear()


def test_setup_logging_idempotent():
    logger = logging.getLogger("termiclaw")
    logger.handlers.clear()
    setup_logging("run1")
    count = len(logger.handlers)
    setup_logging("run2")
    assert len(logger.handlers) == count
    # Cleanup
    logger.handlers.clear()


def test_get_logger_component():
    log = get_logger("agent")
    assert log.name == "termiclaw.agent"


def test_get_logger_different_components():
    log1 = get_logger("planner")
    log2 = get_logger("tmux")
    assert log1.name != log2.name
    assert log1.name == "termiclaw.planner"
    assert log2.name == "termiclaw.tmux"


def test_json_formatter_includes_run_id():
    setup_logging("test-run-123")
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="termiclaw.agent",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["run_id"] == "test-run-123"
    # Cleanup
    logging.getLogger("termiclaw").handlers.clear()


def test_json_formatter_run_id_field_present():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="termiclaw.agent",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="test",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "run_id" in parsed


def test_log_dir_returns_path():
    path = log_dir()
    assert "termiclaw" in str(path)


def test_setup_logging_creates_log_file(tmp_path):
    logger = logging.getLogger("termiclaw")
    logger.handlers.clear()
    with patch.object(log_mod, "log_dir", return_value=tmp_path):
        setup_logging("test-file-run")
        logger.info("hello from test")
        for h in logger.handlers:
            h.flush()
    log_file = tmp_path / "test-file-run.jsonl"
    assert log_file.exists()
    content = log_file.read_text()
    assert "hello from test" in content
    parsed = json.loads(content.strip().splitlines()[-1])
    assert parsed["run_id"] == "test-file-run"
    logger.handlers.clear()


def test_log_levels():
    formatter = JsonFormatter()
    for level_name, level_num in [
        ("DEBUG", logging.DEBUG),
        ("INFO", logging.INFO),
        ("WARNING", logging.WARNING),
        ("ERROR", logging.ERROR),
    ]:
        record = logging.LogRecord(
            name="termiclaw.test",
            level=level_num,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == level_name
