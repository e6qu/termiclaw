"""Tests for termiclaw.artifacts."""

from __future__ import annotations

import json

import pytest

from termiclaw.artifacts import (
    artifacts_dir,
    read_existing,
    refresh_artifacts,
    should_refresh,
)
from termiclaw.models import Config
from termiclaw.state import State


def _state(step: int = 0, tokens: int = 0) -> State:
    return State(
        run_id="r",
        instruction="task",
        tmux_session="s",
        started_at="t",
        status="active",
        current_step=step,
        total_prompt_tokens=tokens,
    )


def test_should_refresh_at_interval(tmp_path):
    cfg = Config(instruction="t", state_dump_interval_turns=10, state_dump_token_threshold=100_000)
    assert should_refresh(_state(step=10), cfg) == "interval"
    assert should_refresh(_state(step=20), cfg) == "interval"
    assert should_refresh(_state(step=11), cfg) == ""


def test_should_refresh_at_token_threshold():
    cfg = Config(instruction="t", state_dump_interval_turns=10, state_dump_token_threshold=100_000)
    assert should_refresh(_state(step=5, tokens=150_000), cfg) == "token_threshold"


def test_should_refresh_skips_step_zero():
    cfg = Config(instruction="t")
    assert should_refresh(_state(step=0), cfg) == ""


def test_artifacts_dir_creates(tmp_path):
    cfg = Config(instruction="t", state_dump_dir_name="my_artifacts")
    a = artifacts_dir(tmp_path, cfg)
    assert a.exists()
    assert a.name == "my_artifacts"


def test_read_existing_empty(tmp_path):
    cfg = Config(instruction="t")
    a = artifacts_dir(tmp_path, cfg)
    result = read_existing(a)
    assert set(result.keys()) == {"what_we_did", "status", "do_next", "plan"}
    assert all(v == "" for v in result.values())


def test_refresh_artifacts_writes_all_four(tmp_path):
    cfg = Config(instruction="t", state_dump_dir_name="artifacts")
    state = _state(step=5)

    def query_fn(_prompt: str) -> str:
        return json.dumps(
            {
                "what_we_did": "# What We Did\n\n- ran ls",
                "status": "# Status\n\nOK",
                "do_next": "# Do Next\n\n1. keep going",
                "plan": "# Plan\n\nexplore",
            }
        )

    refresh_artifacts(state, tmp_path, cfg, "visible screen", query_fn)

    a = tmp_path / "artifacts"
    assert (a / "WHAT_WE_DID.md").read_text() == "# What We Did\n\n- ran ls"
    assert (a / "STATUS.md").read_text() == "# Status\n\nOK"
    assert (a / "DO_NEXT.md").read_text() == "# Do Next\n\n1. keep going"
    assert (a / "PLAN.md").read_text() == "# Plan\n\nexplore"


def test_refresh_artifacts_respects_char_limit(tmp_path):
    cfg = Config(instruction="t", state_dump_dir_name="artifacts", state_dump_max_chars_per_file=10)
    state = _state(step=5)

    def query_fn(_prompt: str) -> str:
        big = "x" * 1000
        return json.dumps({"what_we_did": big, "status": big, "do_next": big, "plan": big})

    refresh_artifacts(state, tmp_path, cfg, "screen", query_fn)
    assert len((tmp_path / "artifacts" / "PLAN.md").read_text()) == 10


def test_refresh_artifacts_propagates_parse_error(tmp_path):
    cfg = Config(instruction="t", state_dump_dir_name="artifacts")
    state = _state(step=5)

    def bad_query(_prompt: str) -> str:
        return "not json at all"

    with pytest.raises(json.JSONDecodeError):
        refresh_artifacts(state, tmp_path, cfg, "screen", bad_query)


def test_refresh_atomic_never_writes_tmp_on_success(tmp_path):
    cfg = Config(instruction="t", state_dump_dir_name="artifacts")
    state = _state(step=5)

    def query_fn(_prompt: str) -> str:
        return json.dumps({"what_we_did": "a", "status": "b", "do_next": "c", "plan": "d"})

    refresh_artifacts(state, tmp_path, cfg, "screen", query_fn)
    a = tmp_path / "artifacts"
    # No leftover .tmp files
    tmps = list(a.glob("*.tmp"))
    assert tmps == []
