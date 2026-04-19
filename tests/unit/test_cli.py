"""Tests for termiclaw.cli."""

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from termiclaw.cli import (
    _attach,
    _build_fork_seed,
    _check_claude,
    _check_docker,
    _eval,
    _export,
    _export_one,
    _failures,
    _finish_update_check,
    _get_local_version,
    _list_runs,
    _mcts,
    _parse_latest_tag,
    _print_run_header,
    _print_trajectory,
    _read_parent_artifacts,
    _resolve_run_dir,
    _resolve_since,
    _run,
    _show,
    _start_update_check,
    _status,
    _tag,
    _version_tuple,
    main,
)
from termiclaw.db import failure_histogram, init_db, insert_failure_tag, insert_run
from termiclaw.models import RunInfo
from termiclaw.state import State


def test_check_docker_present():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _check_docker()


def test_check_docker_missing():
    with (
        patch("termiclaw.cli.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(SystemExit),
    ):
        _check_docker()


def test_check_claude_present():
    with patch("termiclaw.cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        _check_claude()


def test_check_claude_missing():
    with (
        patch("termiclaw.cli.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(SystemExit),
    ):
        _check_claude()


def test_check_docker_command_fails():
    with (
        patch(
            "termiclaw.cli.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "docker"),
        ),
        pytest.raises(SystemExit),
    ):
        _check_docker()


def test_check_claude_command_fails():
    with (
        patch(
            "termiclaw.cli.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "claude"),
        ),
        pytest.raises(SystemExit),
    ):
        _check_claude()


def _run_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "instruction": None,
        "task": None,
        "max_turns": 10,
        "keep_session": False,
        "runs_dir": "./runs",
        "verbose": False,
        "docker_network": "bridge",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_run_task_file_not_found():
    args = _run_args(task="/nonexistent/path/task.txt")
    with (
        patch("termiclaw.cli._check_docker"),
        patch("termiclaw.cli._check_claude"),
        pytest.raises(SystemExit),
    ):
        _run(args)


def test_run_no_instruction():
    args = _run_args()
    with (
        patch("termiclaw.cli._check_docker"),
        patch("termiclaw.cli._check_claude"),
        pytest.raises(SystemExit),
    ):
        _run(args)


def test_run_with_instruction():
    args = _run_args(instruction="do stuff")
    with (
        patch("termiclaw.cli._check_docker"),
        patch("termiclaw.cli._check_claude"),
        patch("termiclaw.cli.agent") as mock_agent,
    ):
        mock_agent.run.return_value = MagicMock(
            run_id="abc",
            status="succeeded",
            current_step=1,
        )
        _run(args)
        mock_agent.run.assert_called_once()
        config = mock_agent.run.call_args[0][0]
        assert config.instruction == "do stuff"
        assert config.docker_network == "bridge"


def test_attach_run_not_found():
    args = argparse.Namespace(run_id="nonexistent123")
    with (
        patch("termiclaw.cli._check_docker"),
        patch("termiclaw.cli.db.init_db"),
        patch("termiclaw.cli.db.get_run", return_value=None),
        pytest.raises(SystemExit),
    ):
        _attach(args)


def test_attach_container_alive():
    args = argparse.Namespace(run_id="abc12345")
    run_info = RunInfo(
        run_id="abc12345xxx",
        instruction="x",
        status="active",
        total_steps=1,
        started_at="t",
        finished_at="",
        tmux_session="termiclaw-abc12345",
        termination_reason="",
        prompt_tokens=0,
        duration="-",
        container_id="cid123",
    )
    with (
        patch("termiclaw.cli._check_docker"),
        patch("termiclaw.cli.db.init_db"),
        patch("termiclaw.cli.db.get_run", return_value=run_info),
        patch("termiclaw.cli.container.is_session_alive", return_value=True),
        patch("termiclaw.cli.container.attach") as mock_attach,
    ):
        _attach(args)
        mock_attach.assert_called_once_with("cid123", "termiclaw-abc12345")


def test_list_runs_empty(tmp_path):
    args = argparse.Namespace(runs_dir=str(tmp_path))
    _list_runs(args)


def test_list_runs_with_data(tmp_path):
    mock_runs = [
        RunInfo(
            run_id="abc12345",
            instruction="fix the bug",
            status="succeeded",
            total_steps=3,
            started_at="2026-04-05T00:00:00Z",
            finished_at="2026-04-05T00:01:00Z",
            tmux_session="t",
            termination_reason="done",
            prompt_tokens=5000,
            duration="1m 0s",
        ),
    ]
    args = argparse.Namespace(runs_dir=str(tmp_path))
    with patch("termiclaw.cli.trajectory.list_runs", return_value=mock_runs):
        _list_runs(args)


def test_list_runs_truncates_instruction(tmp_path):
    long_instruction = "a" * 100
    mock_runs = [
        RunInfo(
            run_id="abc",
            instruction=long_instruction,
            status="succeeded",
            total_steps=1,
            started_at="t",
            finished_at="t",
            tmux_session="t",
            termination_reason="done",
            prompt_tokens=0,
            duration="-",
        ),
    ]
    args = argparse.Namespace(runs_dir=str(tmp_path))
    with patch("termiclaw.cli.trajectory.list_runs", return_value=mock_runs):
        _list_runs(args)


def test_resolve_run_dir_not_found(tmp_path):
    with pytest.raises(SystemExit):
        _resolve_run_dir(tmp_path, "nonexistent")


def test_resolve_run_dir_found(tmp_path):
    run_dir = tmp_path / "abc12345"
    run_dir.mkdir()
    result = _resolve_run_dir(tmp_path, "abc")
    assert result == run_dir


def test_resolve_run_dir_ambiguous(tmp_path):
    (tmp_path / "abc111").mkdir()
    (tmp_path / "abc222").mkdir()
    with pytest.raises(SystemExit):
        _resolve_run_dir(tmp_path, "abc")


def test_resolve_run_dir_nonexistent_parent():
    with pytest.raises(SystemExit):
        _resolve_run_dir(Path("/nonexistent"), "abc")


def test_print_run_header(tmp_path):
    meta = {
        "run_id": "abc",
        "status": "succeeded",
        "instruction": "fix bug",
        "total_steps": 3,
        "started_at": "2026-04-05T00:00:00Z",
        "finished_at": "2026-04-05T00:01:00Z",
    }
    (tmp_path / "run.json").write_text(json.dumps(meta))
    _print_run_header(tmp_path)


def test_print_run_header_no_file(tmp_path):
    _print_run_header(tmp_path)


def test_print_trajectory(tmp_path):
    steps = [
        {
            "step_id": "s1",
            "source": "agent",
            "message": "checking",
            "tool_calls": [{"function_name": "bash_command", "arguments": {"keystrokes": "ls\n"}}],
            "error": None,
        },
        {
            "step_id": "s2",
            "source": "error",
            "message": "",
            "tool_calls": [],
            "error": "parse failed",
        },
    ]
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text("\n".join(json.dumps(s) for s in steps) + "\n")
    _print_trajectory(tmp_path)


def test_print_trajectory_no_file(tmp_path):
    _print_trajectory(tmp_path)


def test_show(tmp_path):
    run_dir = tmp_path / "abc12345"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"run_id": "abc12345", "status": "succeeded"}))
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps({"step_id": "s1", "source": "agent", "message": "hi", "tool_calls": []}) + "\n",
    )
    args = argparse.Namespace(runs_dir=str(tmp_path), run_id="abc")
    _show(args)


def test_status_authenticated():
    auth_json = json.dumps(
        {
            "loggedIn": True,
            "authMethod": "claude.ai",
            "email": "test@example.com",
            "subscriptionType": "max",
        }
    )
    with (
        patch("termiclaw.cli.subprocess.run") as mock_run,
        patch("termiclaw.cli.trajectory.list_runs", return_value=[]),
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=auth_json,
            stderr="",
        )
        _status(argparse.Namespace(runs_dir="./termiclaw_runs"))


def test_status_not_authenticated():
    with (
        patch("termiclaw.cli.subprocess.run") as mock_run,
        patch("termiclaw.cli.trajectory.list_runs", return_value=[]),
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        )
        _status(argparse.Namespace(runs_dir="./termiclaw_runs"))


def test_status_not_found():
    with (
        patch("termiclaw.cli.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(SystemExit),
    ):
        _status(argparse.Namespace(runs_dir="./termiclaw_runs"))


def test_status_timeout():
    with (
        patch(
            "termiclaw.cli.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10),
        ),
        pytest.raises(SystemExit),
    ):
        _status(argparse.Namespace(runs_dir="./termiclaw_runs"))


def test_status_with_runs():
    auth_json = json.dumps(
        {"loggedIn": True, "email": "t@t.com", "subscriptionType": "max", "authMethod": "claude.ai"}
    )
    mock_runs = [
        RunInfo(
            run_id="a",
            instruction="x",
            status="succeeded",
            total_steps=5,
            started_at="t",
            finished_at="t",
            tmux_session="t",
            termination_reason="done",
            prompt_tokens=1000,
            duration="10s",
        ),
        RunInfo(
            run_id="b",
            instruction="y",
            status="failed",
            total_steps=3,
            started_at="t",
            finished_at="t",
            tmux_session="t",
            termination_reason="err",
            prompt_tokens=500,
            duration="5s",
        ),
    ]
    with (
        patch("termiclaw.cli.subprocess.run") as mock_run,
        patch("termiclaw.cli.trajectory.list_runs", return_value=mock_runs),
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=auth_json,
            stderr="",
        )
        _status(argparse.Namespace(runs_dir="./termiclaw_runs"))


def test_version_tuple():
    assert _version_tuple("1.2.3") == (1, 2, 3)
    assert _version_tuple("0.4.0") == (0, 4, 0)
    assert _version_tuple("10.0.1") == (10, 0, 1)
    assert _version_tuple("bad") == (0,)


def test_parse_latest_tag():
    output = (
        "abc123\trefs/tags/termiclaw-v0.1.0\n"
        "def456\trefs/tags/termiclaw-v0.3.0\n"
        "ghi789\trefs/tags/termiclaw-v0.2.0\n"
    )
    assert _parse_latest_tag(output) == "0.3.0"


def test_parse_latest_tag_empty():
    assert _parse_latest_tag("") == ""


def test_parse_latest_tag_no_match():
    assert _parse_latest_tag("abc123\trefs/tags/v1.0.0\n") == ""


def test_get_local_version():
    v = _get_local_version()
    assert v


def test_start_update_check():
    proc = _start_update_check()
    if proc is not None:
        proc.kill()
        proc.wait()


def test_finish_update_check_none():
    _finish_update_check(None)


def test_finish_update_check_no_update(capsys):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (b"abc\trefs/tags/termiclaw-v0.0.1\n", b"")
    mock_proc.returncode = 0
    _finish_update_check(mock_proc)
    captured = capsys.readouterr()
    assert "Update available" not in captured.err


def test_finish_update_check_with_update(capsys):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (b"abc\trefs/tags/termiclaw-v99.0.0\n", b"")
    mock_proc.returncode = 0
    _finish_update_check(mock_proc)
    captured = capsys.readouterr()
    assert "Update available" in captured.err
    assert "99.0.0" in captured.err


def test_finish_update_check_timeout():
    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=2)
    _finish_update_check(mock_proc)
    mock_proc.kill.assert_called_once()


def test_resolve_since_days_suffix():
    iso = _resolve_since("7d")
    assert "T" in iso or "-" in iso


def test_resolve_since_passthrough():
    assert _resolve_since("2026-04-01T00:00:00+00:00") == "2026-04-01T00:00:00+00:00"


def test_export_one_writes_valid_json(tmp_path):
    run_id = "r1"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "instruction": "t",
                "started_at": "s",
                "status": "succeeded",
            },
        ),
    )
    out_path = tmp_path / "out.json"
    _export_one(run_id, tmp_path, out_path)
    data = json.loads(out_path.read_text())
    assert data["schema_version"] == "1.6"
    assert data["run_id"] == run_id


def test_tag_rejects_unknown_category():
    args = argparse.Namespace(
        run_id="nope",
        category="bogus_cat",
        step=None,
        note=None,
    )
    with pytest.raises(SystemExit):
        _tag(args)


def test_failures_empty(capsys, tmp_db_path):
    _ = tmp_db_path
    args = argparse.Namespace(since=None)
    _failures(args)
    captured = capsys.readouterr()
    assert "No failure tags" in captured.err


def test_failures_histogram(capsys, tmp_db_path):
    conn = init_db(tmp_db_path)
    insert_failure_tag(
        conn,
        run_id="a",
        category="stuck_loop",
        step_index=None,
        note=None,
        tagged_at="2026-04-19T00:00:00+00:00",
    )
    conn.close()
    args = argparse.Namespace(since=None)
    _failures(args)
    captured = capsys.readouterr()
    assert "stuck_loop" in captured.err
    assert "TOTAL" in captured.err


def test_failures_since_filter(tmp_db_path, capsys):
    conn = init_db(tmp_db_path)
    insert_failure_tag(
        conn,
        run_id="r",
        category="stuck_loop",
        step_index=None,
        note=None,
        tagged_at="2010-01-01T00:00:00+00:00",
    )
    conn.close()
    args = argparse.Namespace(since="1d")
    _failures(args)
    assert "No failure tags" in capsys.readouterr().err


def test_tag_inserts(tmp_db_path):
    conn = init_db(tmp_db_path)
    insert_run(
        conn,
        State(
            run_id="abc12345",
            instruction="x",
            tmux_session="t",
            started_at="2026-04-19T00:00:00+00:00",
            status="failed",
        ),
    )
    conn.close()
    args = argparse.Namespace(
        run_id="abc",
        category="stuck_loop",
        step=None,
        note="slow",
    )
    _tag(args)
    conn = init_db(tmp_db_path)
    hist = failure_histogram(conn)
    assert hist == [("stuck_loop", 1)]
    conn.close()


def test_tag_rejects_missing_run(tmp_db_path):
    _ = tmp_db_path
    args = argparse.Namespace(
        run_id="nope",
        category="stuck_loop",
        step=None,
        note=None,
    )
    with pytest.raises(SystemExit):
        _tag(args)


def test_export_missing_run_id_without_all():
    args = argparse.Namespace(
        all=False,
        run_id=None,
        out=None,
        format="atif",
        runs_dir="./runs",
    )
    with pytest.raises(SystemExit):
        _export(args)


def test_export_all_no_runs(tmp_path, capsys):
    args = argparse.Namespace(
        all=True,
        run_id=None,
        out=str(tmp_path / "out"),
        format="atif",
        runs_dir=str(tmp_path),
    )
    _export(args)
    captured = capsys.readouterr()
    assert "No runs found" in captured.err


def test_export_one_explicit_run(tmp_path, tmp_db_path):
    _ = tmp_db_path
    run_id = "run_xyz"
    run_dir = Path(tmp_path) / run_id
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {"run_id": run_id, "instruction": "t", "started_at": "s", "status": "succeeded"},
        ),
    )
    args = argparse.Namespace(
        all=False,
        run_id=run_id,
        out=None,
        format="atif",
        runs_dir=str(tmp_path),
    )
    _export(args)
    atif_path = run_dir / f"{run_id}.atif.json"
    assert atif_path.exists()
    data = json.loads(atif_path.read_text())
    assert data["schema_version"] == "1.6"


def test_build_fork_seed_composes_artifacts():
    artifacts = {
        "WHAT_WE_DID.md": "did things",
        "STATUS.md": "in progress",
        "DO_NEXT.md": "next steps",
        "PLAN.md": "the plan",
    }
    seed = _build_fork_seed("continue it", artifacts)
    assert "continue it" in seed
    assert "did things" in seed
    assert "in progress" in seed
    assert "next steps" in seed
    assert "the plan" in seed


def test_read_parent_artifacts_missing(tmp_path):
    result = _read_parent_artifacts(tmp_path)
    assert result == {
        "WHAT_WE_DID.md": "",
        "STATUS.md": "",
        "DO_NEXT.md": "",
        "PLAN.md": "",
    }


def test_read_parent_artifacts_present(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "WHAT_WE_DID.md").write_text("did")
    (artifacts_dir / "STATUS.md").write_text("sta")
    (artifacts_dir / "DO_NEXT.md").write_text("nxt")
    (artifacts_dir / "PLAN.md").write_text("pln")
    result = _read_parent_artifacts(tmp_path)
    assert result == {
        "WHAT_WE_DID.md": "did",
        "STATUS.md": "sta",
        "DO_NEXT.md": "nxt",
        "PLAN.md": "pln",
    }


def test_main_no_command_prints_help(capsys):
    with pytest.raises(SystemExit):
        main([])
    captured = capsys.readouterr()
    assert "termiclaw" in (captured.out + captured.err)


def test_main_list_dispatches(tmp_path):
    main(["list", "--runs-dir", str(tmp_path)])


def test_main_failures_dispatches(tmp_db_path):
    _ = tmp_db_path
    main(["failures"])


def test_main_mcts_show_dispatches(tmp_db_path, capsys):
    _ = tmp_db_path
    with pytest.raises(SystemExit):
        main(["mcts-show", "does_not_exist"])
    assert "No MCTS search" in capsys.readouterr().err


def test_main_export_without_run_id_fails(tmp_db_path):
    _ = tmp_db_path
    with pytest.raises(SystemExit):
        main(["export"])


def test_eval_no_tasks(tmp_path, capsys):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    args = argparse.Namespace(
        tasks_dir=str(tasks_dir),
        repeat=1,
        parallelism=1,
        runs_dir="./runs",
        verbose=False,
        docker_network="bridge",
        max_turns=5,
    )
    _eval(args)
    assert "No task files" in capsys.readouterr().err


def test_eval_invalid_tasks_dir(tmp_path, capsys):
    args = argparse.Namespace(
        tasks_dir=str(tmp_path / "nope"),
        repeat=1,
        parallelism=1,
        runs_dir="./runs",
        verbose=False,
        docker_network="bridge",
        max_turns=5,
    )
    with pytest.raises(SystemExit):
        _eval(args)
    assert "Error:" in capsys.readouterr().err


def test_mcts_missing_task_file(tmp_path, capsys):
    args = argparse.Namespace(
        task=str(tmp_path / "does_not_exist.toml"),
        playouts=1,
        parallelism=1,
        expansion_depth=1,
        runs_dir="./runs",
        verbose=False,
        docker_network="bridge",
    )
    with pytest.raises(SystemExit):
        _mcts(args)
    assert "Error:" in capsys.readouterr().err


def test_mcts_task_without_verifier(tmp_path, capsys):
    task_path = tmp_path / "task.toml"
    task_path.write_text('name = "t"\ninstruction = "do something"\n')
    args = argparse.Namespace(
        task=str(task_path),
        playouts=1,
        parallelism=1,
        expansion_depth=1,
        runs_dir="./runs",
        verbose=False,
        docker_network="bridge",
    )
    with pytest.raises(SystemExit):
        _mcts(args)
    assert "verifier" in capsys.readouterr().err.lower()
