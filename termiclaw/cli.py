"""Command-line interface."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from termiclaw import agent, tmux
from termiclaw.models import Config


def main() -> None:
    """Entry point for the termiclaw CLI."""
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

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        _run(args)
    elif args.command == "attach":
        _attach(args)


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
