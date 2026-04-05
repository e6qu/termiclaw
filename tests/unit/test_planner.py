"""Tests for termiclaw.planner."""

import json
import subprocess
from unittest.mock import patch

import pytest

from termiclaw.planner import build_prompt, extract_usage, parse_response, query_planner

# --- Prompt building ---


def test_build_prompt_basic():
    prompt = build_prompt("fix the bug", "$ _")
    assert "fix the bug" in prompt
    assert "$ _" in prompt
    assert "Summary" not in prompt


def test_build_prompt_with_summary():
    prompt = build_prompt("fix bug", "$ _", summary="We tried X and it failed")
    assert "Summary of progress so far:" in prompt
    assert "We tried X and it failed" in prompt


def test_build_prompt_without_summary():
    prompt = build_prompt("fix bug", "$ _", summary=None)
    assert "Summary" not in prompt


def test_build_prompt_with_qa():
    prompt = build_prompt("fix bug", "$ _", summary="summary text", qa_context="Q: what? A: that")
    assert "summary text" in prompt
    assert "Q: what? A: that" in prompt
    assert "Additional context" in prompt


def test_build_prompt_summary_without_qa():
    prompt = build_prompt("fix bug", "$ _", summary="summary text", qa_context=None)
    assert "summary text" in prompt
    assert "Additional context" not in prompt


# --- JSON auto-fix pipeline ---


def _wrap_envelope(text):
    """Wrap text in a claude -p JSON envelope."""
    return json.dumps({"type": "result", "result": text, "session_id": "test"})


def test_parse_valid_json():
    response = _wrap_envelope(
        json.dumps(
            {
                "analysis": "shell idle",
                "plan": "run ls",
                "commands": [{"keystrokes": "ls\n", "duration": 0.5}],
                "task_complete": False,
            }
        )
    )
    result = parse_response(response)
    assert result.error is None
    assert result.analysis == "shell idle"
    assert result.plan == "run ls"
    assert len(result.commands) == 1
    assert result.commands[0].keystrokes == "ls\n"
    assert result.commands[0].duration == 0.5
    assert result.task_complete is False


def test_parse_markdown_fenced():
    inner = '```json\n{"analysis":"x","plan":"y","commands":[],"task_complete":false}\n```'
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.error is None
    assert result.analysis == "x"


def test_parse_missing_closing_brace():
    inner = '{"analysis":"x","plan":"y","commands":[],"task_complete":false'
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.error is None
    assert result.analysis == "x"


def test_parse_mixed_text():
    inner = (
        "Sure! Here is my response:\n"
        '{"analysis":"x","plan":"y","commands":[],"task_complete":false}\n'
        "Hope that helps!"
    )
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.error is None
    assert result.analysis == "x"


def test_parse_missing_closing_bracket():
    inner = '{"analysis":"x","plan":"y","commands":[{"keystrokes":"ls"'
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.error is None
    assert result.analysis == "x"
    assert len(result.commands) == 1


def test_parse_garbage():
    response = _wrap_envelope("this is not json at all")
    result = parse_response(response)
    assert result.error is not None
    assert "Failed to parse" in result.error


def test_parse_empty_commands():
    inner = json.dumps({"analysis": "x", "plan": "y", "commands": [], "task_complete": False})
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.commands == ()


def test_parse_duration_capped():
    inner = json.dumps(
        {
            "analysis": "x",
            "plan": "y",
            "commands": [{"keystrokes": "make\n", "duration": 120.0}],
            "task_complete": False,
        }
    )
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.commands[0].duration == 60.0


def test_parse_missing_duration():
    inner = json.dumps(
        {
            "analysis": "x",
            "plan": "y",
            "commands": [{"keystrokes": "ls\n"}],
            "task_complete": False,
        }
    )
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.commands[0].duration == 0.5


def test_parse_task_complete_true():
    inner = json.dumps({"analysis": "done", "plan": "none", "commands": [], "task_complete": True})
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.task_complete is True


def test_parse_envelope_unwrap():
    inner_json = '{"analysis":"a","plan":"p","commands":[],"task_complete":false}'
    envelope = json.dumps({"type": "result", "result": inner_json, "session_id": "s123"})
    result = parse_response(envelope)
    assert result.error is None
    assert result.analysis == "a"


def test_parse_bad_envelope():
    result = parse_response("not json")
    assert result.error is not None


def test_parse_empty_result():
    envelope = json.dumps({"type": "result", "result": "", "session_id": "s"})
    result = parse_response(envelope)
    assert result.error is not None


def test_parse_field_order_warning():
    inner = json.dumps({"commands": [], "analysis": "x", "plan": "y", "task_complete": False})
    response = _wrap_envelope(inner)
    result = parse_response(response)
    assert result.error is None
    assert result.warning is not None
    assert "order" in result.warning


# --- Subprocess invocation (mocked) ---


def test_query_planner_success():
    mock_result = subprocess.CompletedProcess(
        args=["claude"], returncode=0, stdout='{"result":"ok"}', stderr=""
    )
    with patch("termiclaw.planner.subprocess.run", return_value=mock_result):
        output = query_planner("test prompt")
    assert output == '{"result":"ok"}'


def test_query_planner_retry_on_error():
    fail = subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr="error")
    success = subprocess.CompletedProcess(
        args=["claude"], returncode=0, stdout='{"result":"ok"}', stderr=""
    )
    with patch("termiclaw.planner.subprocess.run", side_effect=[fail, success]):
        output = query_planner("test", retries=3)
    assert output == '{"result":"ok"}'


def test_query_planner_timeout():
    timeout_exc = subprocess.TimeoutExpired(cmd="claude", timeout=300)
    success = subprocess.CompletedProcess(
        args=["claude"], returncode=0, stdout='{"result":"ok"}', stderr=""
    )
    with patch("termiclaw.planner.subprocess.run", side_effect=[timeout_exc, success]):
        output = query_planner("test", retries=3)
    assert output == '{"result":"ok"}'


def test_query_planner_exhausted_retries():
    fail = subprocess.CompletedProcess(args=["claude"], returncode=1, stdout="", stderr="error")
    with (
        patch("termiclaw.planner.subprocess.run", return_value=fail),
        pytest.raises(RuntimeError, match="failed after 2 attempts"),
    ):
        query_planner("test", retries=2)


def test_query_planner_includes_allowed_tools():
    mock_result = subprocess.CompletedProcess(
        args=["claude"], returncode=0, stdout='{"result":"ok"}', stderr=""
    )
    with patch("termiclaw.planner.subprocess.run", return_value=mock_result) as mock_run:
        query_planner("test prompt")
    cmd_list = mock_run.call_args[0][0]
    assert "--allowedTools" in cmd_list
    idx = cmd_list.index("--allowedTools")
    assert cmd_list[idx + 1] == ""


def test_extract_usage_valid():
    raw = json.dumps(
        {
            "type": "result",
            "result": "ok",
            "total_cost_usd": 0.05,
            "duration_ms": 3000,
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 200},
        }
    )
    u = extract_usage(raw)
    assert u.input_tokens == 150
    assert u.output_tokens == 200
    assert u.cost_usd == 0.05
    assert u.duration_ms == 3000


def test_extract_usage_empty():
    u = extract_usage("")
    assert u.input_tokens == 0
    assert u.cost_usd == 0.0


def test_extract_usage_no_usage_field():
    raw = json.dumps({"type": "result", "result": "ok"})
    u = extract_usage(raw)
    assert u.input_tokens == 0
