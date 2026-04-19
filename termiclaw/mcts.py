"""Monte Carlo Tree Search over termiclaw runs.

Each node represents a fork point `(run_id, step_index)`. Edges are forks
with a prompt variant that reframes the task from that point. MCTS
selects promising nodes via UCB1, expands by forking, simulates the
forked branch to completion, and backpropagates the verifier-based
reward.

Playouts run in parallel via `ThreadPoolExecutor`; each worker spawns
its own Docker container, so branches are fully isolated. The tree
itself is shared, guarded by a single lock.
"""

from __future__ import annotations

import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from termiclaw import agent, db
from termiclaw.errors import TermiclawError
from termiclaw.logging import get_logger
from termiclaw.result import Err
from termiclaw.state import State, coerce_status
from termiclaw.verifier import reward_from_result, verify

if TYPE_CHECKING:
    from termiclaw.models import Config
    from termiclaw.task_file import TaskSpec
    from termiclaw.verifier import VerifierSpec


class AgentRun(Protocol):
    """Callable surface of `agent.run` — injected so tests can substitute it."""

    def __call__(self, config: Config, *, parent: State | None = ...) -> State: ...


_log = get_logger("mcts")

_DEFAULT_UCB_C = math.sqrt(2.0)

_DEFAULT_VARIANTS: tuple[str, ...] = (
    "Try a different approach.",
    "Simplify your plan — the current path seems overcomplicated.",
    "Backtrack one step and reconsider.",
    "Inspect the current state carefully before the next action.",
    "Break the problem into smaller pieces.",
)


class MctsError(TermiclawError):
    """MCTS-specific failure (verifier missing, container failure, etc.)."""


@dataclass(frozen=True, slots=True)
class NodeId:
    """A fork point: (source run_id, step_index to fork from)."""

    run_id: str
    step_index: int


@dataclass
class Node:
    """One node in the search tree."""

    id: NodeId
    parent: NodeId | None
    variant: str = ""  # the re-framing prompt used to reach this node
    children: list[NodeId] = field(default_factory=list)
    visits: int = 0
    total_reward: float = 0.0
    best_reward: float = 0.0
    best_leaf_run_id: str = ""

    @property
    def mean_reward(self) -> float:
        """UCB1 exploitation term."""
        return self.total_reward / self.visits if self.visits else 0.0


def ucb1(node: Node, parent_visits: int, c: float = _DEFAULT_UCB_C) -> float:
    """UCB1 score. Unvisited nodes score infinity (force-visit)."""
    if node.visits == 0:
        return float("inf")
    exploitation = node.mean_reward
    exploration = c * math.sqrt(math.log(max(parent_visits, 1)) / node.visits)
    return exploitation + exploration


@dataclass
class PlayoutResult:
    """One playout's outcome."""

    node_id: NodeId
    leaf_run_id: str
    reward: float
    reason: str


class MctsSearch:
    """One MCTS search over a task.

    Usage:

        search = MctsSearch(task, playouts=20, parallelism=4, config=cfg)
        best = search.run()
        print(f"best reward: {best.best_reward} at {best.best_leaf_run_id}")
    """

    def __init__(  # noqa: PLR0913 — discrete tuning knobs
        self,
        task: TaskSpec,
        *,
        playouts: int,
        parallelism: int,
        config: Config,
        variants: tuple[str, ...] = _DEFAULT_VARIANTS,
        expansion_depth: int = 20,
        ucb_c: float = _DEFAULT_UCB_C,
        agent_run: AgentRun = agent.run,
    ) -> None:
        if task.verifier is None:
            msg = "MCTS requires a task verifier for scoring"
            raise MctsError(msg)
        self.task = task
        self.playouts = playouts
        self.parallelism = parallelism
        self.config = config
        self.variants = variants
        self.expansion_depth = expansion_depth
        self.ucb_c = ucb_c
        self.agent_run = agent_run
        self.search_id = uuid.uuid4().hex[:12]
        self.root = Node(id=NodeId(run_id="root", step_index=0), parent=None)
        self.nodes: dict[NodeId, Node] = {self.root.id: self.root}
        self._lock = threading.Lock()
        self._rng = threading.local()

    def run(self) -> Node:
        """Execute all playouts. Returns the best-scored root child."""
        _log.info(
            "MCTS search starting",
            extra={
                "search_id": self.search_id,
                "playouts": self.playouts,
                "parallelism": self.parallelism,
                "task": self.task.name,
            },
        )
        started_at = datetime.now(tz=UTC).isoformat()
        self._persist_search_start(started_at)
        with ThreadPoolExecutor(max_workers=self.parallelism) as pool:
            futures = [pool.submit(self._playout, i) for i in range(self.playouts)]
            for f in futures:
                result = f.result()
                if result is not None:
                    _log.info(
                        "playout complete",
                        extra={
                            "search_id": self.search_id,
                            "leaf_run_id": result.leaf_run_id,
                            "reward": result.reward,
                            "reason": result.reason,
                        },
                    )
        best = self._best_child(self.root)
        finished_at = datetime.now(tz=UTC).isoformat()
        self._persist_search_finish(finished_at)
        return best if best is not None else self.root

    def _persist_search_start(self, started_at: str) -> None:
        """Insert the mcts_searches row."""
        conn = db.init_db()
        try:
            db.insert_mcts_search(
                conn,
                search_id=self.search_id,
                task_file=self.task.name,
                started_at=started_at,
            )
        finally:
            conn.close()

    def _persist_search_finish(self, finished_at: str) -> None:
        """Mark the search finished and record the best run."""
        conn = db.init_db()
        try:
            db.finish_mcts_search(
                conn,
                search_id=self.search_id,
                finished_at=finished_at,
                total_playouts=self.root.visits,
                best_run_id=self.root.best_leaf_run_id,
                best_reward=self.root.best_reward,
            )
        finally:
            conn.close()

    def _persist_node(self, node: Node) -> None:
        """Upsert a single node's current counters into SQLite."""
        conn = db.init_db()
        try:
            db.upsert_mcts_node(
                conn,
                node_id=f"{node.id.run_id}:{node.id.step_index}",
                search_id=self.search_id,
                parent_node_id=(
                    f"{node.parent.run_id}:{node.parent.step_index}" if node.parent else None
                ),
                run_id=node.id.run_id,
                step_index=node.id.step_index,
                variant=node.variant,
                visits=node.visits,
                total_reward=node.total_reward,
                best_reward=node.best_reward,
                best_leaf_run_id=node.best_leaf_run_id,
            )
        finally:
            conn.close()

    def _playout(self, playout_idx: int) -> PlayoutResult | None:
        """One expand-simulate-backprop iteration."""
        try:
            parent_node = self._select()
            variant = self._pick_variant(playout_idx)
            run_id, passed_reward, reason = self._simulate(parent_node, variant)
            node = self._record_new_node(parent_node, run_id, variant)
            self._backprop(node, passed_reward)
            return PlayoutResult(
                node_id=node.id,
                leaf_run_id=run_id,
                reward=passed_reward,
                reason=reason,
            )
        except TermiclawError as e:
            _log.exception("playout failed", extra={"error": str(e)})
            return None

    def _select(self) -> Node:
        """Descend the tree using UCB1 until a node with no children is reached."""
        with self._lock:
            current = self.root
            while current.children:
                parent_visits = max(current.visits, 1)
                best_id = max(
                    current.children,
                    key=lambda cid: ucb1(self.nodes[cid], parent_visits, self.ucb_c),
                )
                current = self.nodes[best_id]
            return current

    def _pick_variant(self, playout_idx: int) -> str:
        """Choose a re-framing prompt. Round-robin over the variant pool."""
        if not self.variants:
            return ""
        return self.variants[playout_idx % len(self.variants)]

    def _simulate(
        self,
        parent_node: Node,
        variant: str,
    ) -> tuple[str, float, str]:
        """Run a fresh child playout; return (leaf_run_id, reward, reason)."""
        instruction = _compose_instruction(self.task.instruction, variant)
        playout_config = _replace_instruction(self.config, instruction, self.expansion_depth)
        parent_state = _parent_state_for_fork(parent_node)
        state = self.agent_run(playout_config, parent=parent_state)
        if not state.container_id:
            return (state.run_id, 0.0, "container_never_started")
        if self.task.verifier is None:
            return (state.run_id, 0.0, "no_verifier")  # guarded in __init__
        reward, reason = _score_run(state, self.task.verifier)
        return (state.run_id, reward, reason)

    def _record_new_node(
        self,
        parent_node: Node,
        run_id: str,
        variant: str,
    ) -> Node:
        """Insert a child node under the parent, return it."""
        with self._lock:
            node = Node(
                id=NodeId(run_id=run_id, step_index=0),
                parent=parent_node.id,
                variant=variant,
            )
            self.nodes[node.id] = node
            parent_node.children.append(node.id)
            return node

    def _backprop(self, node: Node, reward: float) -> None:
        """Propagate reward up the tree."""
        updated: list[Node] = []
        with self._lock:
            current: Node | None = node
            while current is not None:
                current.visits += 1
                current.total_reward += reward
                if reward > current.best_reward:
                    current.best_reward = reward
                    current.best_leaf_run_id = node.id.run_id
                updated.append(current)
                if current.parent is None:
                    break
                current = self.nodes.get(current.parent)
        # Persist outside the lock to avoid holding it during SQLite I/O.
        for n in updated:
            self._persist_node(n)

    def _best_child(self, node: Node) -> Node | None:
        """Return the child with the highest mean reward."""
        with self._lock:
            if not node.children:
                return None
            return max(
                (self.nodes[cid] for cid in node.children),
                key=lambda n: n.mean_reward,
            )


def _compose_instruction(base: str, variant: str) -> str:
    """Concatenate the base instruction with a variant re-framing."""
    if not variant:
        return base
    return f"{base}\n\nHint: {variant}"


def _replace_instruction(config: Config, instruction: str, max_turns: int) -> Config:
    """Clone config with a new instruction and tightened max_turns for playouts."""
    return replace(config, instruction=instruction, max_turns=max_turns)


def _parent_state_for_fork(parent_node: Node) -> State | None:
    """Reconstruct a minimal parent State for `agent.run(parent=...)`.

    Loads the parent run's `claude_session_id` and other metadata from
    SQLite. The returned State is a read-only snapshot used to wire
    `--fork-session` on the child's first planner call. Returns None
    if the parent is the root (no fork — start fresh).
    """
    if parent_node.parent is None:
        return None
    conn = db.init_db()
    try:
        info = db.get_run(conn, parent_node.id.run_id)
    finally:
        conn.close()
    if info is None or not info.claude_session_id:
        return None
    return State(
        run_id=info.run_id,
        instruction=info.instruction,
        tmux_session=info.tmux_session,
        started_at=info.started_at,
        status=coerce_status(info.status),
        container_id=info.container_id,
        claude_session_id=info.claude_session_id,
        current_step=info.total_steps,
    )


def _score_run(state: State, spec: VerifierSpec) -> tuple[float, str]:
    """Run the verifier against the completed run's container.

    The container may already be gone (runs with `--keep-session=False`
    destroy their container on finish). In that case we cannot verify —
    return 0.0 with reason `container_gone`.
    """
    if not state.container_id:
        return (0.0, "container_gone")
    result = verify(state.container_id, spec)
    if isinstance(result, Err):
        return (0.0, f"verifier_error: {result.error}")
    return (reward_from_result(result.value), result.value.reason)
