# termiclaw

A Terminus-style terminal agent that uses Claude Code as a planner and tmux as the execution substrate.

## What it does

Termiclaw runs an observe-decide-act loop: it captures terminal output from a tmux session, asks Claude Code what to do next, sends keystrokes, and repeats. One tool only --- raw keystrokes through tmux. No file-edit tools, no bash abstractions.

```
Operator                    Termiclaw Agent                 tmux session
   |                              |                              |
   |--- run "fix the test" ------>|                              |
   |                              |--- provision session ------->|
   |                              |                              |
   |                              |--- capture terminal -------->|
   |                              |<-- terminal output ----------|
   |                              |                              |
   |                              |--- claude -p (planner) ----->|
   |                              |<-- {commands, analysis} -----|
   |                              |                              |
   |                              |--- send-keys "pytest\n" ---->|
   |                              |<-- test output --------------|
   |                              |                              |
   |                              |   ... repeat until done ...  |
   |                              |                              |
   |<-- succeeded (3 steps) ------|--- destroy session --------->|
```

Inspired by [Terminus-2](https://github.com/harbor-framework/harbor) from the Harbor Framework.

## Requirements

- Python 3.13+
- [tmux](https://github.com/tmux/tmux)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with an active subscription

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

# Options
termiclaw run "fix the bug" --max-turns 50 --keep-session --verbose
```

Every run produces a trajectory log in `./termiclaw_runs/<run-id>/`:
- `trajectory.jsonl` --- step-by-step ATIF-format log
- `run.json` --- run metadata (status, timing, termination reason)

## How it works

- **Planner**: Stateless `claude -p` calls. Each call gets the task, a summary of progress, and current terminal state. Returns JSON with `analysis`, `plan`, `commands`, and `task_complete`.
- **Execution**: Raw tmux keystrokes via `send-keys`. Special keys (`C-c`, `Enter`, `Up`) sent natively; literal text sent with `-l` flag.
- **Summarization**: Three-subagent pipeline (summary, questions, answers) triggered when context grows large. Mirrors Terminus-2's handoff strategy.
- **Double-finish**: The planner must confirm `task_complete=true` twice to prevent premature exits.

## License

[AGPL-3.0-or-later](LICENSE)
