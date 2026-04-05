"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from termiclaw import agent, tmux, trajectory
from termiclaw.models import Config

_REPO_URL = "https://github.com/e6qu/termiclaw.git"
_TAG_PATTERN = re.compile(r"refs/tags/termiclaw-v(\d+\.\d+\.\d+)$")


def main() -> None:
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

    attach_parser = sub.add_parser("attach", help="Attach to a running tmux session")
    attach_parser.add_argument("run_id", help="Run ID (or prefix)")

    list_parser = sub.add_parser("list", help="List all runs")
    list_parser.add_argument("--runs-dir", default="./termiclaw_runs")

    show_parser = sub.add_parser("show", help="Show run trajectory")
    show_parser.add_argument("run_id", help="Run ID (or prefix)")
    show_parser.add_argument("--runs-dir", default="./termiclaw_runs")

    status_parser = sub.add_parser("status", help="Show auth status and usage summary")
    status_parser.add_argument("--runs-dir", default="./termiclaw_runs")

    args = parser.parse_args()

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

    _finish_update_check(update_check)


def _run(args: argparse.Namespace) -> None:
    """Start a new run."""
    _check_tmux()
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
    )

    state = agent.run(config)
    sys.stderr.write(f"Run {state.run_id} finished: {state.status} ({state.current_step} steps)\n")


def _attach(args: argparse.Namespace) -> None:
    """Attach to an existing tmux session."""
    prefix = f"termiclaw-{args.run_id[:8]}"
    if tmux.is_session_alive(prefix):
        tmux.attach_session(prefix)
        return
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write("Error: no tmux sessions found\n")
        sys.exit(1)
    matches = [s for s in result.stdout.strip().splitlines() if s.startswith(prefix)]
    if len(matches) == 1:
        tmux.attach_session(matches[0])
    elif len(matches) > 1:
        sys.stderr.write(
            f"Error: ambiguous run_id, matches: {', '.join(matches)}\n",
        )
        sys.exit(1)
    else:
        sys.stderr.write(f"Error: no session found matching '{prefix}'\n")
        sys.exit(1)


def _check_tmux() -> None:
    """Verify tmux is installed."""
    try:
        subprocess.run(
            ["tmux", "-V"],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.stderr.write(
            "Error: tmux not found. Install it:\n"
            "  macOS: brew install tmux\n"
            "  Ubuntu: sudo apt install tmux\n",
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
        f"{'ID':<10} {'STATUS':<10} {'STEPS':>5} {'CHARS':>8} {'DURATION':>10}  INSTRUCTION\n",
    )
    sys.stderr.write("-" * 100 + "\n")
    for r in runs:
        instruction = r.instruction.replace("\n", " ")
        if len(instruction) > max_instr:
            instruction = instruction[: max_instr - 3] + "..."
        sys.stderr.write(
            f"{r.run_id[:8]:<10} {r.status:<10} {r.total_steps:>5} "
            f"{r.prompt_chars:>8,} {r.duration:>10}  {instruction}\n",
        )


def _show(args: argparse.Namespace) -> None:
    """Show a run's trajectory."""
    run_dir = _resolve_run_dir(Path(args.runs_dir), args.run_id)
    _print_run_header(run_dir)
    _print_trajectory(run_dir)


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
    total_chars = sum(r.prompt_chars for r in runs)
    succeeded = sum(1 for r in runs if r.status == "succeeded")
    failed = sum(1 for r in runs if r.status == "failed")
    sys.stderr.write(f"Local runs: {len(runs)} ({succeeded} succeeded, {failed} failed)\n")
    sys.stderr.write(f"Total steps: {total_steps}\n")
    sys.stderr.write(f"Total prompt chars: {total_chars:,}\n")


def _start_update_check() -> subprocess.Popen[bytes] | None:
    """Start a background git ls-remote to check for newer versions."""
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
    except Exception:  # noqa: BLE001
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
