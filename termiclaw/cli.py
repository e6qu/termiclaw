"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

from termiclaw import agent, atif, container, db, trajectory
from termiclaw.mcts import MctsError, MctsSearch
from termiclaw.models import Config
from termiclaw.result import Err
from termiclaw.state import State, coerce_status
from termiclaw.tagging import is_valid_category, valid_categories
from termiclaw.task_file import load_task, load_tasks_dir

if TYPE_CHECKING:
    from collections.abc import Sequence

_REPO_URL = "https://github.com/e6qu/termiclaw.git"
_TAG_PATTERN = re.compile(r"refs/tags/termiclaw-v(\d+\.\d+\.\d+)$")


def main(argv: Sequence[str] | None = None) -> None:  # noqa: PLR0912, PLR0915, C901
    """Entry point for the termiclaw CLI."""
    update_check = _start_update_check()

    parser = argparse.ArgumentParser(
        prog="termiclaw",
        description="Terminus-style terminal agent",
    )
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Start a new run")
    run_parser.add_argument("instruction", nargs="?", help="Task instruction")
    run_parser.add_argument("--task", help="Read instruction from file")
    run_parser.add_argument("--max-turns", type=int, default=1_000_000)
    run_parser.add_argument("--keep-session", action="store_true")
    run_parser.add_argument("--runs-dir", default="./termiclaw_runs")
    run_parser.add_argument("--verbose", action="store_true")
    run_parser.add_argument(
        "--docker-network",
        default="bridge",
        help="Docker network for the run container (default: bridge)",
    )

    attach_parser = sub.add_parser(
        "attach",
        help="Attach to the tmux session inside a run's container",
    )
    attach_parser.add_argument("run_id", help="Run ID (or prefix)")

    list_parser = sub.add_parser("list", help="List all runs")
    list_parser.add_argument("--runs-dir", default="./termiclaw_runs")

    show_parser = sub.add_parser("show", help="Show run trajectory")
    show_parser.add_argument("run_id", help="Run ID (or prefix)")
    show_parser.add_argument("--runs-dir", default="./termiclaw_runs")

    status_parser = sub.add_parser("status", help="Show auth status and usage summary")
    status_parser.add_argument("--runs-dir", default="./termiclaw_runs")

    mcts_parser = sub.add_parser(
        "mcts",
        help="Run MCTS optimization over a task (parallel forks + verifier scoring)",
    )
    mcts_parser.add_argument("--task", required=True, help="Path to a TOML task file")
    mcts_parser.add_argument("--playouts", type=int, default=10)
    mcts_parser.add_argument("--parallelism", type=int, default=1)
    mcts_parser.add_argument("--expansion-depth", type=int, default=20)
    mcts_parser.add_argument("--runs-dir", default="./termiclaw_runs")
    mcts_parser.add_argument("--verbose", action="store_true")
    mcts_parser.add_argument("--docker-network", default="bridge")

    mcts_show_parser = sub.add_parser(
        "mcts-show",
        help="Render an MCTS search tree from SQLite",
    )
    mcts_show_parser.add_argument("search_id", help="MCTS search ID (or prefix)")

    eval_parser = sub.add_parser(
        "eval",
        help="Run a directory of task TOML files and report pass/fail",
    )
    eval_parser.add_argument("tasks_dir", help="Directory containing .toml task files")
    eval_parser.add_argument("--repeat", type=int, default=1)
    eval_parser.add_argument("--parallelism", type=int, default=1)
    eval_parser.add_argument("--runs-dir", default="./termiclaw_runs")
    eval_parser.add_argument("--verbose", action="store_true")
    eval_parser.add_argument("--docker-network", default="bridge")
    eval_parser.add_argument("--max-turns", type=int, default=50)

    export_parser = sub.add_parser(
        "export",
        help="Export a run's trajectory to ATIF v1.6 JSON",
    )
    export_parser.add_argument("run_id", nargs="?", help="Run ID (or prefix)")
    export_parser.add_argument("--all", action="store_true", help="Export every run")
    export_parser.add_argument("--out", help="Output directory (with --all) or file path")
    export_parser.add_argument("--format", default="atif", choices=["atif"])
    export_parser.add_argument("--runs-dir", default="./termiclaw_runs")

    tag_parser = sub.add_parser(
        "tag",
        help="Tag a run (or step within it) with a failure category",
    )
    tag_parser.add_argument("run_id", help="Run ID (or prefix)")
    tag_parser.add_argument(
        "--category",
        required=True,
        help="Failure category (e.g. stuck_loop, parse_failure, premature_completion)",
    )
    tag_parser.add_argument("--step", type=int, help="Specific step index (optional)")
    tag_parser.add_argument("--note", help="Optional free-text note")

    failures_parser = sub.add_parser(
        "failures",
        help="Show a histogram of tagged failures",
    )
    failures_parser.add_argument("--since", help="ISO timestamp or duration like '7d'")

    fork_parser = sub.add_parser(
        "fork",
        help="Fork an existing run into a fresh Claude Code session + container",
    )
    fork_parser.add_argument("run_id", help="Parent run ID (or prefix)")
    fork_parser.add_argument("--task", help="Override the task instruction")
    fork_parser.add_argument("--runs-dir", default="./termiclaw_runs")
    fork_parser.add_argument("--max-turns", type=int, default=1_000_000)
    fork_parser.add_argument("--keep-session", action="store_true")
    fork_parser.add_argument("--verbose", action="store_true")
    fork_parser.add_argument("--docker-network", default="bridge")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        _finish_update_check(update_check)
        sys.exit(1)

    if args.command == "run":
        _run(args)
    elif args.command == "attach":
        _attach(args)
    elif args.command == "list":
        _list_runs(args)
    elif args.command == "show":
        _show(args)
    elif args.command == "status":
        _status(args)
    elif args.command == "fork":
        _fork(args)
    elif args.command == "mcts":
        _mcts(args)
    elif args.command == "mcts-show":
        _mcts_show(args)
    elif args.command == "eval":
        _eval(args)
    elif args.command == "export":
        _export(args)
    elif args.command == "tag":
        _tag(args)
    elif args.command == "failures":
        _failures(args)

    _finish_update_check(update_check)


def _run(args: argparse.Namespace) -> None:
    """Start a new run."""
    _check_docker()
    _check_claude()

    instruction = args.instruction
    if args.task:
        task_path = Path(args.task)
        if not task_path.exists():
            sys.stderr.write(f"Error: task file not found: {args.task}\n")
            sys.exit(1)
        instruction = task_path.read_text().strip()
    if not instruction:
        sys.stderr.write("Error: provide an instruction or --task file\n")
        sys.exit(1)

    config = Config(
        instruction=instruction,
        max_turns=args.max_turns,
        keep_session=args.keep_session,
        verbose=args.verbose,
        runs_dir=args.runs_dir,
        docker_network=args.docker_network,
    )

    state = agent.run(config)
    sys.stderr.write(f"Run {state.run_id} finished: {state.status} ({state.current_step} steps)\n")


def _fork(args: argparse.Namespace) -> None:
    """Fork an existing run into a fresh Claude Code session + container."""
    _check_docker()
    _check_claude()

    conn = db.init_db()
    parent_info = db.get_run(conn, args.run_id)
    conn.close()
    if parent_info is None:
        sys.stderr.write(f"Error: no run found matching '{args.run_id}'\n")
        sys.exit(1)

    parent_run_dir = Path(args.runs_dir) / parent_info.run_id
    artifacts = _read_parent_artifacts(parent_run_dir)
    task = args.task or parent_info.instruction
    seed_prompt = _build_fork_seed(task, artifacts)

    config = Config(
        instruction=seed_prompt,
        max_turns=args.max_turns,
        keep_session=args.keep_session,
        verbose=args.verbose,
        runs_dir=args.runs_dir,
        docker_network=args.docker_network,
    )

    parent_state = State(
        run_id=parent_info.run_id,
        instruction=parent_info.instruction,
        tmux_session=parent_info.tmux_session,
        started_at=parent_info.started_at,
        status=coerce_status(parent_info.status),
        claude_session_id=parent_info.claude_session_id,
        container_id=parent_info.container_id,
        current_step=parent_info.total_steps,
    )
    state = agent.run(config, parent=parent_state)
    sys.stderr.write(
        f"Fork {state.run_id} finished: {state.status} ({state.current_step} steps, "
        f"parent={parent_info.run_id[:8]})\n",
    )


def _read_parent_artifacts(run_dir: Path) -> dict[str, str]:
    """Read the four artifact files from the parent run."""
    artifacts_path = run_dir / "artifacts"
    result: dict[str, str] = {}
    for filename in ("WHAT_WE_DID.md", "STATUS.md", "DO_NEXT.md", "PLAN.md"):
        path = artifacts_path / filename
        result[filename] = path.read_text(encoding="utf-8") if path.exists() else ""
    return result


def _build_fork_seed(task: str, artifacts: dict[str, str]) -> str:
    """Compose the seed prompt for a forked run."""
    return (
        f"You are continuing work forked from a prior session.\n\n"
        f"Task: {task}\n\n"
        "Prior session summary (from artifacts):\n\n"
        f"## What we already did\n{artifacts['WHAT_WE_DID.md']}\n\n"
        f"## Current status\n{artifacts['STATUS.md']}\n\n"
        f"## Suggested next steps\n{artifacts['DO_NEXT.md']}\n\n"
        f"## Plan\n{artifacts['PLAN.md']}"
    )


def _mcts(args: argparse.Namespace) -> None:
    """Run MCTS optimization over a task."""
    task_result = load_task(Path(args.task))
    if isinstance(task_result, Err):
        sys.stderr.write(f"Error: {task_result.error}\n")
        sys.exit(1)
    task = task_result.value
    if task.verifier is None:
        sys.stderr.write(
            "Error: MCTS requires a task verifier. Add a [verifier] section to the task file.\n",
        )
        sys.exit(1)

    _check_docker()
    _check_claude()

    config = Config(
        instruction=task.instruction,
        max_turns=args.expansion_depth,
        verbose=args.verbose,
        runs_dir=args.runs_dir,
        docker_network=args.docker_network,
        verifier=task.verifier,
    )
    try:
        search = MctsSearch(
            task,
            playouts=args.playouts,
            parallelism=args.parallelism,
            config=config,
            expansion_depth=args.expansion_depth,
        )
    except MctsError as e:
        sys.stderr.write(f"MCTS error: {e}\n")
        sys.exit(1)

    best = search.run()
    sys.stderr.write(
        f"\nMCTS search {search.search_id} finished: "
        f"best_reward={best.best_reward} via run={best.best_leaf_run_id[:8]}\n",
    )


def _mcts_show(args: argparse.Namespace) -> None:
    """Render an MCTS tree to stderr as an ASCII drawing."""
    conn = db.init_db()
    search = db.get_mcts_search(conn, args.search_id)
    if search is None:
        cursor = conn.execute(
            "SELECT search_id FROM mcts_searches WHERE search_id LIKE ? LIMIT 2",
            (f"{args.search_id}%",),
        )
        matches = [row[0] for row in cursor]
        if len(matches) == 1:
            search = db.get_mcts_search(conn, matches[0])
        else:
            sys.stderr.write(f"No MCTS search found matching '{args.search_id}'\n")
            sys.exit(1)
    assert search is not None  # noqa: S101 — narrow type after prefix lookup
    nodes = db.get_mcts_nodes(conn, str(search["search_id"]))
    conn.close()

    sys.stderr.write(
        f"Search {search['search_id']} — task: {search['task_file']} — "
        f"{search['total_playouts']} playouts — "
        f"best reward {search['best_reward']}\n\n",
    )
    _render_tree(nodes)


def _render_tree(nodes: list[dict[str, str | int | float | None]]) -> None:
    """ASCII-render an MCTS tree from flat node rows."""
    by_parent: dict[str | None, list[dict[str, str | int | float | None]]] = {}
    for n in nodes:
        key = n["parent_node_id"]
        parent_key = key if isinstance(key, str) or key is None else str(key)
        by_parent.setdefault(parent_key, []).append(n)

    def _print(parent_id: str | None, indent: str) -> None:
        children = by_parent.get(parent_id, [])
        for i, node in enumerate(children):
            is_last = i == len(children) - 1
            connector = "└─ " if is_last else "├─ "
            visits = node["visits"]
            visits_n = visits if isinstance(visits, int) else 0
            total = node["total_reward"]
            total_f = total if isinstance(total, (int, float)) else 0.0
            mean = (total_f / visits_n) if visits_n else 0.0
            variant = node["variant"] or "(root)"
            run_short = str(node["run_id"])[:8]
            sys.stderr.write(
                f"{indent}{connector}[{variant}] run_{run_short} "
                f"(visits {visits_n}, mean {mean:.2f}, best {node['best_reward']})\n",
            )
            next_indent = indent + ("   " if is_last else "│  ")
            _print(str(node["node_id"]), next_indent)

    _print(None, "")


def _eval(args: argparse.Namespace) -> None:
    """Run a directory of task TOML files and report pass/fail."""
    tasks_result = load_tasks_dir(Path(args.tasks_dir))
    if isinstance(tasks_result, Err):
        sys.stderr.write(f"Error: {tasks_result.error}\n")
        sys.exit(1)
    tasks = tasks_result.value
    if not tasks:
        sys.stderr.write(f"No task files found in {args.tasks_dir}\n")
        return

    _check_docker()
    _check_claude()

    _print_eval_header()
    totals_pass = 0
    totals_fail = 0
    for task in tasks:
        passed = 0
        failed = 0
        for _ in range(args.repeat):
            config = Config(
                instruction=task.instruction,
                max_turns=args.max_turns,
                verbose=args.verbose,
                runs_dir=args.runs_dir,
                docker_network=args.docker_network,
                verifier=task.verifier,
            )
            state = agent.run(config)
            if state.status == "succeeded":
                passed += 1
            else:
                failed += 1
        totals_pass += passed
        totals_fail += failed
        _print_eval_row(task.name, passed, failed, args.repeat)
    _print_eval_totals(totals_pass, totals_fail, totals_pass + totals_fail)


def _print_eval_header() -> None:
    sys.stderr.write(f"\n{'TASK':<32} {'PASS':>5} {'FAIL':>5} {'RATE':>6}\n")
    sys.stderr.write("-" * 52 + "\n")


def _print_eval_row(name: str, passed: int, failed: int, total: int) -> None:
    rate = f"{int(100 * passed / total)}%" if total else "n/a"
    sys.stderr.write(f"{name[:32]:<32} {passed:>5} {failed:>5} {rate:>6}\n")


def _print_eval_totals(passed: int, failed: int, total: int) -> None:
    sys.stderr.write("-" * 52 + "\n")
    rate = f"{int(100 * passed / total)}%" if total else "n/a"
    sys.stderr.write(f"{'TOTAL':<32} {passed:>5} {failed:>5} {rate:>6}\n")


def _attach(args: argparse.Namespace) -> None:
    """Attach to the tmux session inside a run's container."""
    _check_docker()
    conn = db.init_db()
    run_info = db.get_run(conn, args.run_id)
    conn.close()
    if run_info is None:
        sys.stderr.write(f"Error: no run found matching '{args.run_id}'\n")
        sys.exit(1)
    if not run_info.container_id:
        sys.stderr.write(
            f"Error: run {run_info.run_id[:8]} has no container_id recorded.\n",
        )
        sys.exit(1)
    if not container.is_session_alive(run_info.container_id, run_info.tmux_session):
        sys.stderr.write(
            f"Error: container {run_info.container_id[:12]} is not running "
            "(was it started with --keep-session?)\n",
        )
        sys.exit(1)
    container.attach(run_info.container_id, run_info.tmux_session)


def _check_docker() -> None:
    """Verify Docker is installed and running."""
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.stderr.write(
            "Error: Docker not running or not installed. Install + start Docker:\n"
            "  macOS: https://docs.docker.com/desktop/install/mac-install/\n"
            "  Linux: https://docs.docker.com/engine/install/\n"
            "Termiclaw v1.0 requires Docker; host tmux is no longer supported.\n",
        )
        sys.exit(1)


def _list_runs(args: argparse.Namespace) -> None:
    """List all runs."""
    runs = trajectory.list_runs(args.runs_dir)
    if not runs:
        sys.stderr.write("No runs found.\n")
        return
    max_instr = 60
    sys.stderr.write(
        f"{'ID':<10} {'STATUS':<10} {'STEPS':>5} {'TOKENS':>8} {'DURATION':>10}  INSTRUCTION\n",
    )
    sys.stderr.write("-" * 100 + "\n")
    for r in runs:
        instruction = r.instruction.replace("\n", " ")
        if len(instruction) > max_instr:
            instruction = instruction[: max_instr - 3] + "..."
        sys.stderr.write(
            f"{r.run_id[:8]:<10} {r.status:<10} {r.total_steps:>5} "
            f"{r.prompt_tokens:>8,} {r.duration:>10}  {instruction}\n",
        )


def _show(args: argparse.Namespace) -> None:
    """Show a run's trajectory."""
    run_dir = _resolve_run_dir(Path(args.runs_dir), args.run_id)
    _print_run_header(run_dir)
    _print_trajectory(run_dir)
    _print_artifacts(run_dir)


def _print_artifacts(run_dir: Path) -> None:
    """Print the four state-dump artifacts if they exist."""
    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return
    sys.stderr.write("\n--- Artifacts ---\n")
    for filename in ("WHAT_WE_DID.md", "STATUS.md", "DO_NEXT.md", "PLAN.md"):
        path = artifacts_dir / filename
        if path.exists():
            sys.stderr.write(f"\n### {filename}\n")
            sys.stderr.write(path.read_text(encoding="utf-8"))
            sys.stderr.write("\n")


def _resolve_run_dir(runs_path: Path, prefix: str) -> Path:
    """Find a unique run directory matching a prefix."""
    if not runs_path.exists():
        sys.stderr.write("No runs found.\n")
        sys.exit(1)
    matches = [d for d in runs_path.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    if not matches:
        sys.stderr.write(f"No run found matching '{prefix}'\n")
        sys.exit(1)
    if len(matches) > 1:
        sys.stderr.write(f"Ambiguous: {', '.join(d.name for d in matches)}\n")
        sys.exit(1)
    return matches[0]


def _print_run_header(run_dir: Path) -> None:
    """Print run metadata header."""
    run_json = run_dir / "run.json"
    if not run_json.exists():
        return
    meta = json.loads(run_json.read_text(encoding="utf-8"))
    for key in ("run_id", "status", "instruction", "total_steps", "started_at", "finished_at"):
        sys.stderr.write(f"{key}: {meta.get(key, '?')}\n")
    sys.stderr.write("\n")


def _print_trajectory(run_dir: Path) -> None:
    """Print trajectory steps."""
    traj = run_dir / "trajectory.jsonl"
    if not traj.exists():
        sys.stderr.write("No trajectory found.\n")
        return
    for i, line in enumerate(traj.read_text(encoding="utf-8").strip().splitlines(), 1):
        try:
            step = json.loads(line)
        except json.JSONDecodeError:
            continue
        source = step.get("source", "?")
        message = step.get("message", "")
        error = step.get("error")
        sys.stderr.write(f"--- Step {i} [{source}] ---\n")
        if message:
            sys.stderr.write(f"  {message}\n")
        for tc in step.get("tool_calls", []):
            fn = tc.get("function_name", "?")
            ks = tc.get("arguments", {}).get("keystrokes", "")
            sys.stderr.write(f"  > {fn}: {ks!r}\n" if ks else f"  > {fn}\n")
        if error:
            sys.stderr.write(f"  ERROR: {error}\n")
        sys.stderr.write("\n")


def _status(args: argparse.Namespace) -> None:
    """Show Claude Code auth status and local usage summary."""
    _show_auth_status()
    _show_usage_summary(args.runs_dir)


def _show_auth_status() -> None:
    """Print Claude Code authentication info."""
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        sys.stderr.write("Error: Claude Code not found.\n")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        sys.stderr.write("Error: Claude Code timed out.\n")
        sys.exit(1)
    if result.returncode != 0:
        sys.stderr.write("Claude Code: not authenticated\n")
        return
    try:
        auth = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(result.stdout)
        return
    sys.stderr.write(f"Email: {auth.get('email', '?')}\n")
    sys.stderr.write(f"Subscription: {auth.get('subscriptionType', '?')}\n")
    sys.stderr.write(f"Auth method: {auth.get('authMethod', '?')}\n")
    sys.stderr.write(f"Logged in: {auth.get('loggedIn', False)}\n\n")


def _show_usage_summary(runs_dir: str) -> None:
    """Print local usage summary from trajectory data."""
    runs = trajectory.list_runs(runs_dir)
    if not runs:
        sys.stderr.write("No local runs found.\n")
        return
    total_steps = sum(r.total_steps for r in runs)
    total_tokens = sum(r.prompt_tokens for r in runs)
    succeeded = sum(1 for r in runs if r.status == "succeeded")
    failed = sum(1 for r in runs if r.status == "failed")
    sys.stderr.write(f"Local runs: {len(runs)} ({succeeded} succeeded, {failed} failed)\n")
    sys.stderr.write(f"Total steps: {total_steps}\n")
    sys.stderr.write(f"Total prompt tokens: {total_tokens:,}\n")


def _start_update_check() -> subprocess.Popen[bytes] | None:
    """Start a background git ls-remote to check for newer versions.

    `TERMICLAW_SKIP_UPDATE_CHECK=1` disables the network call (used in
    tests to keep unit runs hermetic).
    """
    if os.environ.get("TERMICLAW_SKIP_UPDATE_CHECK"):
        return None
    try:
        return subprocess.Popen(
            ["git", "ls-remote", "--tags", _REPO_URL],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None


_UPDATE_CHECK_TIMEOUT_S = 2


def _finish_update_check(proc: subprocess.Popen[bytes] | None) -> None:
    """Wait for the background version check and print update notice if needed."""
    if proc is None:
        return
    try:
        stdout, _ = proc.communicate(timeout=_UPDATE_CHECK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        return
    if proc.returncode != 0:
        return
    local_version = _get_local_version()
    if not local_version:
        return
    remote_version = _parse_latest_tag(stdout.decode("utf-8", errors="replace"))
    if not remote_version:
        return
    if _version_tuple(remote_version) > _version_tuple(local_version):
        sys.stderr.write(
            f"\nUpdate available: {local_version} -> {remote_version}\n"
            f"Run: uv tool upgrade termiclaw\n",
        )


def _get_local_version() -> str:
    """Get the installed version of termiclaw."""
    try:
        return version("termiclaw")
    except PackageNotFoundError:
        return ""


def _parse_latest_tag(ls_remote_output: str) -> str:
    """Extract the highest version from git ls-remote --tags output."""
    best = ""
    for line in ls_remote_output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:  # noqa: PLR2004
            continue
        match = _TAG_PATTERN.search(parts[1])
        if match:
            candidate = match.group(1)
            if not best or _version_tuple(candidate) > _version_tuple(best):
                best = candidate
    return best


def _version_tuple(ver: str) -> tuple[int, ...]:
    """Convert '1.2.3' to (1, 2, 3) for comparison."""
    try:
        return tuple(int(x) for x in ver.split("."))
    except ValueError:
        return (0,)


def _export(args: argparse.Namespace) -> None:
    """Export one or all runs to ATIF v1.6 JSON."""
    runs_dir = Path(args.runs_dir)
    if args.all:
        out_dir = Path(args.out) if args.out else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        runs = trajectory.list_runs(args.runs_dir)
        if not runs:
            sys.stderr.write("No runs found.\n")
            return
        for r in runs:
            _export_one(r.run_id, runs_dir, out_dir / f"{r.run_id}.atif.json")
        sys.stderr.write(f"Exported {len(runs)} run(s) to {out_dir}\n")
        return

    if not args.run_id:
        sys.stderr.write("Error: provide a run_id or use --all\n")
        sys.exit(1)

    conn = db.init_db()
    run_info = db.get_run(conn, args.run_id)
    conn.close()
    resolved = run_info.run_id if run_info else args.run_id
    out_path = Path(args.out) if args.out else runs_dir / resolved / f"{resolved}.atif.json"
    _export_one(resolved, runs_dir, out_path)
    sys.stderr.write(f"Wrote {out_path}\n")


def _export_one(run_id: str, runs_dir: Path, out_path: Path) -> None:
    """Write a single ATIF JSON file or exit on error."""
    result = atif.export_run(run_id, runs_dir)
    if isinstance(result, Err):
        sys.stderr.write(f"Error exporting {run_id}: {result.error}\n")
        sys.exit(1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(atif.atif_to_json(result.value), encoding="utf-8")


def _tag(args: argparse.Namespace) -> None:
    """Insert a failure tag for a run."""
    if not is_valid_category(args.category):
        sys.stderr.write(
            f"Error: unknown category '{args.category}'. Valid: {', '.join(valid_categories())}\n",
        )
        sys.exit(1)
    conn = db.init_db()
    run_info = db.get_run(conn, args.run_id)
    if run_info is None:
        sys.stderr.write(f"Error: no run found matching '{args.run_id}'\n")
        conn.close()
        sys.exit(1)
    db.insert_failure_tag(
        conn,
        run_id=run_info.run_id,
        category=args.category,
        step_index=args.step,
        note=args.note,
        tagged_at=datetime.now(tz=UTC).isoformat(),
    )
    conn.close()
    sys.stderr.write(
        f"Tagged run {run_info.run_id[:8]} as '{args.category}'"
        + (f" at step {args.step}" if args.step is not None else "")
        + "\n",
    )


def _failures(args: argparse.Namespace) -> None:
    """Print a histogram of failure tags."""
    since_iso = _resolve_since(args.since) if args.since else None
    conn = db.init_db()
    hist = db.failure_histogram(conn, since_iso=since_iso)
    conn.close()
    if not hist:
        sys.stderr.write("No failure tags recorded.\n")
        return
    total = sum(count for _, count in hist)
    sys.stderr.write(f"{'CATEGORY':<28} {'COUNT':>6} {'PCT':>6}\n")
    sys.stderr.write("-" * 42 + "\n")
    for category, count in hist:
        pct = f"{100 * count / total:.0f}%"
        sys.stderr.write(f"{category:<28} {count:>6} {pct:>6}\n")
    sys.stderr.write("-" * 42 + "\n")
    sys.stderr.write(f"{'TOTAL':<28} {total:>6}\n")


_DURATION_DAYS_RE = re.compile(r"^(\d+)d$")


def _resolve_since(value: str) -> str:
    """Parse '7d' or an ISO timestamp; return an ISO timestamp."""
    m = _DURATION_DAYS_RE.match(value)
    if m:
        days = int(m.group(1))
        return (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
    return value


def _check_claude() -> None:
    """Verify Claude Code is installed."""
    try:
        subprocess.run(
            ["claude", "--version"],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.stderr.write(
            "Error: Claude Code not found. Install it:\n"
            "  npm install -g @anthropic-ai/claude-code\n",
        )
        sys.exit(1)
