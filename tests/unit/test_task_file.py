"""Tests for termiclaw.task_file."""

from __future__ import annotations

from termiclaw.result import Err, Ok
from termiclaw.task_file import load_task, load_tasks_dir


def _write_toml(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_task_minimal(tmp_path):
    path = tmp_path / "hello.toml"
    _write_toml(path, 'instruction = "do a thing"\n')
    result = load_task(path)
    assert isinstance(result, Ok)
    task = result.value
    assert task.name == "hello"
    assert task.instruction == "do a thing"
    assert task.verifier is None


def test_load_task_with_verifier(tmp_path):
    path = tmp_path / "create_file.toml"
    _write_toml(
        path,
        'instruction = "create /tmp/x"\n\n'
        "[verifier]\n"
        'command = "cat /tmp/x"\n'
        "expected_exit = 0\n"
        'expected_output_pattern = "^hello"\n'
        "timeout_seconds = 5\n",
    )
    result = load_task(path)
    assert isinstance(result, Ok)
    task = result.value
    assert task.verifier is not None
    assert task.verifier.command == "cat /tmp/x"
    assert task.verifier.expected_output_pattern == "^hello"
    assert task.verifier.timeout_seconds == 5.0


def test_load_task_missing_instruction(tmp_path):
    path = tmp_path / "bad.toml"
    _write_toml(path, '[verifier]\ncommand = "x"\n')
    assert isinstance(load_task(path), Err)


def test_load_task_invalid_toml(tmp_path):
    path = tmp_path / "bad.toml"
    _write_toml(path, "not = valid toml [[[")
    assert isinstance(load_task(path), Err)


def test_load_tasks_dir_multiple(tmp_path):
    _write_toml(tmp_path / "a.toml", 'instruction = "task a"\n')
    _write_toml(tmp_path / "b.toml", 'instruction = "task b"\n')
    result = load_tasks_dir(tmp_path)
    assert isinstance(result, Ok)
    assert [t.name for t in result.value] == ["a", "b"]


def test_load_tasks_dir_not_a_dir(tmp_path):
    path = tmp_path / "nope"
    assert isinstance(load_tasks_dir(path), Err)


def test_load_tasks_dir_empty(tmp_path):
    result = load_tasks_dir(tmp_path)
    assert isinstance(result, Ok)
    assert result.value == []
