"""Tests for termiclaw.atif — ATIF v1.6 export."""

from __future__ import annotations

import json

from termiclaw.atif import atif_to_json, export_run
from termiclaw.result import Err, Ok


def _write_run(tmp_path, *, run_id: str = "run_abc") -> str:
    """Create a minimal runs_dir/<run_id>/ with run.json + trajectory.jsonl."""
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "instruction": "do a thing",
                "started_at": "2026-04-19T00:00:00+00:00",
                "finished_at": "2026-04-19T00:05:00+00:00",
                "status": "succeeded",
                "claude_session_id": "sess-1",
            }
        ),
    )
    (run_dir / "trajectory.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "step_id": "s1",
                        "timestamp": "2026-04-19T00:00:01+00:00",
                        "source": "planner",
                        "message": "think",
                        "tool_calls": [
                            {
                                "function_name": "bash_command",
                                "arguments": {"keystrokes": "ls\\n", "duration": 1.0},
                            },
                        ],
                        "observation": {"terminal_output": "file.txt\n"},
                        "metrics": {
                            "prompt_tokens": 100,
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "cost_usd": 0.001,
                            "planner_duration_ms": 250,
                        },
                        "is_copied_context": False,
                        "error": None,
                    }
                ),
                json.dumps(
                    {
                        "step_id": "s2",
                        "timestamp": "2026-04-19T00:00:02+00:00",
                        "source": "planner",
                        "message": "done",
                        "tool_calls": [{"function_name": "mark_task_complete", "arguments": {}}],
                        "observation": {"terminal_output": ""},
                        "metrics": {},
                        "is_copied_context": False,
                        "error": None,
                    }
                ),
            ]
        )
        + "\n",
    )
    return run_id


def test_export_missing_run_dir(tmp_path):
    result = export_run("nope", tmp_path)
    assert isinstance(result, Err)
    assert "not a directory" in str(result.error)


def test_export_missing_run_json(tmp_path):
    (tmp_path / "empty").mkdir()
    result = export_run("empty", tmp_path)
    assert isinstance(result, Err)
    assert "missing" in str(result.error)


def test_export_roundtrip(tmp_path):
    run_id = _write_run(tmp_path)
    result = export_run(run_id, tmp_path)
    assert isinstance(result, Ok)
    run = result.value
    assert run.schema_version == "1.6"
    assert run.run_id == run_id
    assert run.session_id == "sess-1"
    assert run.instruction == "do a thing"
    assert run.status == "succeeded"
    assert len(run.steps) == 2

    s1 = run.steps[0]
    assert s1.step_id == "s1"
    assert len(s1.tool_calls) == 1
    assert s1.tool_calls[0].function_name == "bash_command"
    assert s1.observation.terminal_output == "file.txt\n"
    assert s1.metrics.prompt_tokens == 100
    assert s1.metrics.cost_usd == 0.001

    s2 = run.steps[1]
    assert s2.tool_calls[0].function_name == "mark_task_complete"
    assert s2.metrics.prompt_tokens == 0  # empty metrics → defaults


def test_atif_to_json_produces_valid_json(tmp_path):
    run_id = _write_run(tmp_path)
    result = export_run(run_id, tmp_path)
    assert isinstance(result, Ok)
    text = atif_to_json(result.value)
    parsed = json.loads(text)
    assert parsed["schema_version"] == "1.6"
    assert parsed["run_id"] == run_id
    assert len(parsed["steps"]) == 2


def test_export_empty_trajectory(tmp_path):
    """A run without trajectory.jsonl returns Ok with zero steps."""
    run_dir = tmp_path / "r"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": "r",
                "instruction": "t",
                "started_at": "x",
                "status": "succeeded",
            }
        ),
    )
    result = export_run("r", tmp_path)
    assert isinstance(result, Ok)
    assert result.value.steps == []


def test_export_skips_malformed_trajectory_lines(tmp_path):
    """Malformed JSONL lines are skipped, not fatal."""
    run_id = "r"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {"run_id": run_id, "instruction": "t", "started_at": "x", "status": "succeeded"}
        ),
    )
    (run_dir / "trajectory.jsonl").write_text(
        '{"step_id": "ok", "timestamp": "t", "source": "p", "message": "m", '
        '"tool_calls": [], "observation": {}, "metrics": {}, '
        '"is_copied_context": false}\n'
        "this is not json\n"
        "[1, 2, 3]\n"  # valid JSON but not a dict
        "\n",
    )
    result = export_run(run_id, tmp_path)
    assert isinstance(result, Ok)
    assert len(result.value.steps) == 1
    assert result.value.steps[0].step_id == "ok"
