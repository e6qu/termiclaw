"""Tests for termiclaw.mcts — pure parts (ucb1, tree ops) that need no Docker."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from termiclaw.db import get_mcts_search, init_db
from termiclaw.mcts import (
    MctsError,
    MctsSearch,
    Node,
    NodeId,
    _compose_instruction,
    _parent_state_for_fork,
    _replace_instruction,
    _score_run,
    ucb1,
)
from termiclaw.models import Config
from termiclaw.state import State
from termiclaw.task_file import TaskSpec
from termiclaw.verifier import VerifierSpec

if TYPE_CHECKING:
    from termiclaw.mcts import AgentRun


def _task(*, with_verifier: bool = True) -> TaskSpec:
    verifier = VerifierSpec(command="true") if with_verifier else None
    return TaskSpec(name="t", instruction="do a thing", verifier=verifier)


def _node(visits: int = 0, reward: float = 0.0) -> Node:
    return Node(
        id=NodeId(run_id="r", step_index=0),
        parent=None,
        visits=visits,
        total_reward=reward,
    )


def _fixed_run(state: State) -> AgentRun:
    """Build an AgentRun substitute that always returns `state`."""

    def _run(config: Config, *, parent: State | None = None) -> State:
        _ = (config, parent)
        return state

    return _run


def test_ucb1_unvisited_is_infinity():
    assert ucb1(_node(visits=0), parent_visits=1) == float("inf")


def test_ucb1_balances_exploitation_exploration():
    high_visits = _node(visits=10, reward=5.0)
    low_visits = _node(visits=2, reward=1.0)
    parent_visits = 12
    assert ucb1(low_visits, parent_visits) > ucb1(high_visits, parent_visits)


def test_ucb1_mean_reward_matters():
    a = _node(visits=3, reward=3.0)
    b = _node(visits=3, reward=0.0)
    assert ucb1(a, parent_visits=6) > ucb1(b, parent_visits=6)


def test_ucb1_c_tuning():
    node = _node(visits=3, reward=1.5)
    default_c = ucb1(node, parent_visits=6, c=math.sqrt(2))
    high_c = ucb1(node, parent_visits=6, c=10.0)
    assert high_c > default_c


def test_node_mean_reward_no_visits():
    assert _node(visits=0).mean_reward == 0.0


def test_node_mean_reward_simple():
    assert _node(visits=4, reward=2.0).mean_reward == 0.5


def test_compose_instruction_no_variant():
    assert _compose_instruction("do X", "") == "do X"


def test_compose_instruction_with_variant():
    result = _compose_instruction("do X", "try something else")
    assert "do X" in result
    assert "try something else" in result
    assert "Hint:" in result


def test_replace_instruction_preserves_other_fields():
    cfg = Config(instruction="old", max_turns=1000, docker_network="bridge")
    new_cfg = _replace_instruction(cfg, "new instruction", 20)
    assert new_cfg.instruction == "new instruction"
    assert new_cfg.max_turns == 20
    assert new_cfg.docker_network == "bridge"


def test_mcts_requires_verifier():
    task = _task(with_verifier=False)
    cfg = Config(instruction="x")
    with pytest.raises(MctsError, match="verifier"):
        MctsSearch(task, playouts=1, parallelism=1, config=cfg)


def test_mcts_search_initializes_tree():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    assert search.root.id.run_id == "root"
    assert search.root.visits == 0
    assert len(search.nodes) == 1


def test_mcts_backprop_updates_ancestors():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    child_id = NodeId(run_id="child", step_index=0)
    child = Node(id=child_id, parent=search.root.id)
    search.nodes[child_id] = child
    search.root.children.append(child_id)

    search._backprop(child, reward=1.0)  # noqa: SLF001
    assert child.visits == 1
    assert child.total_reward == 1.0
    assert search.root.visits == 1
    assert search.root.total_reward == 1.0
    assert search.root.best_reward == 1.0
    assert search.root.best_leaf_run_id == "child"


def test_mcts_best_child_picks_highest_mean():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    a_id = NodeId(run_id="a", step_index=0)
    b_id = NodeId(run_id="b", step_index=0)
    search.nodes[a_id] = Node(id=a_id, parent=search.root.id, visits=2, total_reward=0.5)
    search.nodes[b_id] = Node(id=b_id, parent=search.root.id, visits=2, total_reward=1.5)
    search.root.children.extend([a_id, b_id])
    best = search._best_child(search.root)  # noqa: SLF001
    assert best is not None
    assert best.id == b_id


def test_mcts_best_child_none_for_leaf():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    assert search._best_child(search.root) is None  # noqa: SLF001


def test_mcts_pick_variant_rotates():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(
        task,
        playouts=0,
        parallelism=1,
        config=cfg,
        variants=("A", "B", "C"),
    )
    assert search._pick_variant(0) == "A"  # noqa: SLF001
    assert search._pick_variant(1) == "B"  # noqa: SLF001
    assert search._pick_variant(3) == "A"  # noqa: SLF001


def test_mcts_pick_variant_empty_pool():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg, variants=())
    assert search._pick_variant(0) == ""  # noqa: SLF001


def test_mcts_select_descends_to_leaf():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    child_id = NodeId(run_id="child", step_index=0)
    grand_id = NodeId(run_id="grand", step_index=0)
    child = Node(id=child_id, parent=search.root.id, visits=1, total_reward=1.0)
    grand = Node(id=grand_id, parent=child_id, visits=0, total_reward=0.0)
    search.nodes[child_id] = child
    search.nodes[grand_id] = grand
    search.root.children.append(child_id)
    child.children.append(grand_id)
    search.root.visits = 1
    leaf = search._select()  # noqa: SLF001
    assert leaf.id == grand_id


def test_mcts_record_new_node_links_parent():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    node = search._record_new_node(search.root, run_id="new_run", variant="try X")  # noqa: SLF001
    assert node.parent == search.root.id
    assert node.id in search.nodes
    assert node.id in search.root.children


def test_parent_state_for_fork_root_returns_none():
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    assert _parent_state_for_fork(search.root) is None


def test_parent_state_for_fork_missing_db_entry(tmp_db_path):
    _ = tmp_db_path
    child = Node(
        id=NodeId(run_id="nope_run_id", step_index=0),
        parent=NodeId(run_id="root", step_index=0),
    )
    assert _parent_state_for_fork(child) is None


def test_mcts_run_zero_playouts(tmp_db_path):
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(task, playouts=0, parallelism=1, config=cfg)
    best = search.run()
    assert best.id.run_id == "root"
    conn = init_db(tmp_db_path)
    row = get_mcts_search(conn, search.search_id)
    assert row is not None
    assert row["total_playouts"] == 0
    conn.close()


def test_mcts_simulate_container_never_started(tmp_db_path):
    _ = tmp_db_path
    fake_state = State(
        run_id="simulated_run",
        instruction="x",
        tmux_session="t",
        started_at="s",
        status="failed",
    )
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(
        task,
        playouts=0,
        parallelism=1,
        config=cfg,
        agent_run=_fixed_run(fake_state),
    )
    run_id, reward, reason = search._simulate(search.root, "variant")  # noqa: SLF001
    assert run_id == "simulated_run"
    assert reward == 0.0
    assert reason == "container_never_started"


def test_mcts_playout_wraps_simulate(tmp_db_path):
    _ = tmp_db_path
    fake_state = State(
        run_id="playout_run",
        instruction="x",
        tmux_session="t",
        started_at="s",
        status="failed",
    )
    task = _task()
    cfg = Config(instruction="x")
    search = MctsSearch(
        task,
        playouts=0,
        parallelism=1,
        config=cfg,
        agent_run=_fixed_run(fake_state),
    )
    result = search._playout(0)  # noqa: SLF001
    assert result is not None
    assert result.leaf_run_id == "playout_run"
    assert result.reward == 0.0
    assert result.reason == "container_never_started"
    assert search.root.visits == 1


def test_score_run_container_gone():
    state = State(
        run_id="r",
        instruction="x",
        tmux_session="t",
        started_at="2026-04-19T00:00:00+00:00",
        status="succeeded",
    )
    assert state.container_id == ""
    reward, reason = _score_run(state, VerifierSpec(command="true"))
    assert reward == 0.0
    assert reason == "container_gone"
