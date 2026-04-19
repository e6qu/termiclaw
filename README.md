# termiclaw

[![CI](https://github.com/e6qu/termiclaw/actions/workflows/ci.yml/badge.svg)](https://github.com/e6qu/termiclaw/actions/workflows/ci.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green)](LICENSE)
[![Code lines](https://img.shields.io/badge/code-6319%20lines-blue)]
[![Test lines](https://img.shields.io/badge/tests-5936%20lines-blue)]

A Terminus-style terminal agent that uses Claude Code as a planner and tmux-in-a-Docker-container as the execution substrate. Inspired by [Terminus-2](https://github.com/harbor-framework/harbor) from the Harbor Framework. See [TERMINUS.md](TERMINUS.md) for the reference implementation analysis.

Current release: **v1.4** (functional-core / imperative-shell split, frozen `State`, typed `Ports`). Since v1.0, all runs provision a fresh Docker container (Terminal-Bench-parity `ubuntu:24.04` base with tmux) for isolation — the image is built locally on first run from the repo's `Dockerfile` and tagged by content hash (`termiclaw-base:<sha256[:12]>`). Roadmap and shipped-per-version log in [PLAN.md](PLAN.md).

## How it works

Termiclaw runs an observe-decide-act loop: capture terminal output, ask Claude Code what to do, send keystrokes, repeat. One tool only --- raw keystrokes through tmux, inside a Docker container.

```
Operator                    Termiclaw Agent                 tmux session
   |                              |                              |
   |--- run "fix the test" ------>|                              |
   |                              |--- provision session ------->|
   |                              |--- capture terminal -------->|
   |                              |--- claude -p (planner) ----->|
   |                              |<-- {commands, analysis} -----|
   |                              |--- send-keys "pytest\n" ---->|
   |                              |<-- test output --------------|
   |                              |   ... repeat until done ...  |
   |<-- succeeded (3 steps) ------|--- destroy session --------->|
```

- **Planner**: Stateless `claude -p` calls returning JSON with `analysis`, `plan`, `commands`, `task_complete`
- **Execution**: Raw tmux `send-keys` inside a Docker container. Special keys (`C-c`, `Enter`) sent natively; literal text with `-l` flag
- **Summarization**: Three-subagent pipeline (summary, questions, answers) — runs asynchronously on a background thread so stall detection keeps observing the tmux session
- **Stall self-unblock**: identical-observation / repeat-command detection escalates nudge → force-interrupt
- **Double-finish**: Planner must confirm `task_complete=true` twice to prevent premature exits
- **MCTS optimization**: parallel forks of a verifier-scored task via `termiclaw mcts`, `--fork-session` at the Claude Code level

For the product spec and non-functional requirements, see [SPEC.md](SPEC.md); for the architectural comparison against Terminus, see [docs/DESIGN.md](docs/DESIGN.md).

## Requirements

- Python 3.13+
- [Docker](https://docs.docker.com/get-docker/) (daemon running)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with an active subscription

Note: tmux runs inside the container, not on the host. You only need the Docker daemon.

## Installation

```bash
uv tool install git+https://github.com/e6qu/termiclaw.git
```

Installs to `~/.local/bin/termiclaw` with an isolated virtualenv. No root required.

To update:

```bash
uv tool upgrade termiclaw
```

## Usage

```bash
# Run a task
termiclaw run "create a Python file that prints hello world"

# Run from a task file
termiclaw run --task task.txt

# Watch the agent work (in another terminal)
termiclaw attach <run-id>

# List all past runs
termiclaw list

# Show a run's trajectory step by step
termiclaw show <run-id>

# Check Claude Code quota
termiclaw status

# Fork an existing run into a fresh session
termiclaw fork <run-id>

# Run a directory of tasks with verifiers and report pass/fail
termiclaw eval tasks/ --repeat 3

# MCTS: search for a solution via parallel forks scored by a verifier
termiclaw mcts --task tasks/hard.toml --playouts 20 --parallelism 4

# Render an MCTS search as an ASCII tree
termiclaw mcts-show <search-id>

# Export a run's trajectory to ATIF v1.6 JSON (Terminal-Bench submission format)
termiclaw export <run-id> --format atif

# Tag a failed run with a category; view a histogram of tagged failures
termiclaw tag <run-id> --category stuck_loop --note "looped on bad regex"
termiclaw failures --since 7d

# Options
termiclaw run "fix the bug" --max-turns 50 --keep-session --verbose
```

Every run produces a trajectory log in `./termiclaw_runs/<run-id>/`:
- `trajectory.jsonl` --- step-by-step ATIF-format log
- `run.json` --- run metadata (status, timing, termination reason)

Structured JSONL logs are also written to:
- **macOS**: `~/Library/Logs/termiclaw/<run-id>.jsonl`
- **Linux**: `~/.local/state/termiclaw/log/<run-id>.jsonl`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing, and PR guidelines.

## Documentation

| Document | Description |
|----------|-------------|
| [PLAN.md](PLAN.md) | Roadmap; shipped-per-version log; lint rules in force |
| [SPEC.md](SPEC.md) | Product spec: purpose, principles, non-functional requirements |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture narrative and comparison against Terminus |
| [TERMINUS.md](TERMINUS.md) | Terminus-2 source-code reference (pre-v1.0 snapshot) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and PR process |
| [BUGS.md](BUGS.md) | Resolved bugs and false positives |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## License

[AGPL-3.0-or-later](LICENSE)
