"""Tests for MCTS SQLite persistence and `mcts-show` rendering helpers."""

from __future__ import annotations

import argparse

import pytest

from termiclaw.cli import _mcts_show, _render_tree
from termiclaw.db import (
    failure_histogram,
    finish_mcts_search,
    get_mcts_nodes,
    get_mcts_search,
    init_db,
    insert_failure_tag,
    insert_mcts_search,
    upsert_mcts_node,
)
from termiclaw.mcts import MctsSearch, Node, NodeId
from termiclaw.models import Config
from termiclaw.task_file import TaskSpec
from termiclaw.verifier import VerifierSpec


def test_round_trip_search(tmp_path):
    conn = init_db(tmp_path / "test.db")
    insert_mcts_search(
        conn,
        search_id="s1",
        task_file="fix.toml",
        started_at="2026-04-19T00:00:00+00:00",
    )
    finish_mcts_search(
        conn,
        search_id="s1",
        finished_at="2026-04-19T00:05:00+00:00",
        total_playouts=3,
        best_run_id="run_best",
        best_reward=1.0,
    )
    search = get_mcts_search(conn, "s1")
    assert search is not None
    assert search["total_playouts"] == 3
    assert search["best_run_id"] == "run_best"
    assert search["best_reward"] == 1.0
    conn.close()


def test_upsert_node_updates_counters(tmp_path):
    conn = init_db(tmp_path / "test.db")
    insert_mcts_search(
        conn,
        search_id="s1",
        task_file="t.toml",
        started_at="2026-04-19T00:00:00+00:00",
    )
    for visits, reward in ((1, 0.5), (2, 1.5), (3, 2.0)):
        upsert_mcts_node(
            conn,
            node_id="root:0",
            search_id="s1",
            parent_node_id=None,
            run_id="root",
            step_index=0,
            variant="",
            visits=visits,
            total_reward=reward,
            best_reward=reward,
            best_leaf_run_id="leaf",
        )
    rows = get_mcts_nodes(conn, "s1")
    assert len(rows) == 1
    assert rows[0]["visits"] == 3
    assert rows[0]["total_reward"] == 2.0
    conn.close()


def test_get_mcts_nodes_orders_children_under_parent(tmp_path):
    conn = init_db(tmp_path / "test.db")
    insert_mcts_search(
        conn,
        search_id="s",
        task_file="t.toml",
        started_at="2026-04-19T00:00:00+00:00",
    )
    upsert_mcts_node(
        conn,
        node_id="root:0",
        search_id="s",
        parent_node_id=None,
        run_id="root",
        step_index=0,
        variant="",
        visits=2,
        total_reward=1.0,
        best_reward=0.5,
        best_leaf_run_id="a",
    )
    upsert_mcts_node(
        conn,
        node_id="a:0",
        search_id="s",
        parent_node_id="root:0",
        run_id="a",
        step_index=0,
        variant="try X",
        visits=1,
        total_reward=0.5,
        best_reward=0.5,
        best_leaf_run_id="a",
    )
    upsert_mcts_node(
        conn,
        node_id="b:0",
        search_id="s",
        parent_node_id="root:0",
        run_id="b",
        step_index=0,
        variant="try Y",
        visits=1,
        total_reward=0.5,
        best_reward=0.5,
        best_leaf_run_id="b",
    )
    rows = get_mcts_nodes(conn, "s")
    assert len(rows) == 3
    parent_ids = [r["parent_node_id"] for r in rows]
    assert parent_ids == [None, "root:0", "root:0"]
    conn.close()


def test_render_tree_emits_ascii_structure(capsys):
    nodes: list[dict[str, str | int | float | None]] = [
        {
            "node_id": "root:0",
            "parent_node_id": None,
            "run_id": "root",
            "step_index": 0,
            "variant": "",
            "visits": 3,
            "total_reward": 1.5,
            "best_reward": 1.0,
            "best_leaf_run_id": "leaf1234",
        },
        {
            "node_id": "a:0",
            "parent_node_id": "root:0",
            "run_id": "aaaa1111",
            "step_index": 0,
            "variant": "try X",
            "visits": 2,
            "total_reward": 1.0,
            "best_reward": 1.0,
            "best_leaf_run_id": "aaaa1111",
        },
        {
            "node_id": "b:0",
            "parent_node_id": "root:0",
            "run_id": "bbbb2222",
            "step_index": 0,
            "variant": "try Y",
            "visits": 1,
            "total_reward": 0.5,
            "best_reward": 0.5,
            "best_leaf_run_id": "bbbb2222",
        },
    ]
    _render_tree(nodes)
    out = capsys.readouterr().err
    assert "[(root)] run_root" in out
    assert "[try X] run_aaaa1111" in out
    assert "[try Y] run_bbbb2222" in out
    assert "├─" in out
    assert "└─" in out


def test_mcts_search_persists_start_and_finish(tmp_db_path):
    task = TaskSpec(name="t", instruction="x", verifier=VerifierSpec(command="true"))
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    search._persist_search_start("2026-04-19T00:00:00+00:00")  # noqa: SLF001
    conn = init_db(tmp_db_path)
    row = get_mcts_search(conn, search.search_id)
    assert row is not None
    assert row["task_file"] == "t"
    conn.close()

    search.root.visits = 5
    search.root.best_reward = 0.8
    search.root.best_leaf_run_id = "leaf"
    search._persist_search_finish("2026-04-19T00:05:00+00:00")  # noqa: SLF001
    conn = init_db(tmp_db_path)
    row = get_mcts_search(conn, search.search_id)
    assert row is not None
    assert row["total_playouts"] == 5
    assert row["best_run_id"] == "leaf"
    assert row["best_reward"] == 0.8
    conn.close()


def test_mcts_search_persist_node(tmp_db_path):
    task = TaskSpec(name="t", instruction="x", verifier=VerifierSpec(command="true"))
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    search._persist_search_start("2026-04-19T00:00:00+00:00")  # noqa: SLF001
    node = Node(
        id=NodeId(run_id="child", step_index=0),
        parent=search.root.id,
        variant="try X",
        visits=3,
        total_reward=1.5,
        best_reward=0.8,
        best_leaf_run_id="leafrun",
    )
    search._persist_node(node)  # noqa: SLF001

    conn = init_db(tmp_db_path)
    rows = get_mcts_nodes(conn, search.search_id)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "child"
    assert rows[0]["visits"] == 3
    conn.close()


def test_mcts_show_missing_search(tmp_db_path, capsys):
    _ = tmp_db_path
    args = argparse.Namespace(search_id="does_not_exist")
    with pytest.raises(SystemExit):
        _mcts_show(args)
    captured = capsys.readouterr()
    assert "No MCTS search found" in captured.err


def test_mcts_show_renders_tree(tmp_db_path, capsys):
    conn = init_db(tmp_db_path)
    insert_mcts_search(
        conn,
        search_id="search1",
        task_file="task.toml",
        started_at="2026-04-19T00:00:00+00:00",
    )
    finish_mcts_search(
        conn,
        search_id="search1",
        finished_at="2026-04-19T00:05:00+00:00",
        total_playouts=2,
        best_run_id="leaf",
        best_reward=1.0,
    )
    upsert_mcts_node(
        conn,
        node_id="root:0",
        search_id="search1",
        parent_node_id=None,
        run_id="root",
        step_index=0,
        variant="",
        visits=2,
        total_reward=1.0,
        best_reward=1.0,
        best_leaf_run_id="leaf",
    )
    conn.close()
    args = argparse.Namespace(search_id="search1")
    _mcts_show(args)
    out = capsys.readouterr().err
    assert "search1" in out
    assert "task.toml" in out
    assert "run_root" in out


def test_failure_tags_roundtrip(tmp_path):
    conn = init_db(tmp_path / "test.db")
    insert_failure_tag(
        conn,
        run_id="r1",
        category="stuck_loop",
        step_index=None,
        note=None,
        tagged_at="2026-04-19T00:00:00+00:00",
    )
    insert_failure_tag(
        conn,
        run_id="r2",
        category="stuck_loop",
        step_index=None,
        note=None,
        tagged_at="2026-04-19T00:01:00+00:00",
    )
    insert_failure_tag(
        conn,
        run_id="r3",
        category="parse_failure",
        step_index=2,
        note="bad json",
        tagged_at="2026-04-19T00:02:00+00:00",
    )
    hist = failure_histogram(conn)
    assert hist[0] == ("stuck_loop", 2)
    assert ("parse_failure", 1) in hist
    conn.close()
