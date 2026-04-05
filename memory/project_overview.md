---
name: Termiclaw project overview
description: Core design decisions for Termiclaw — a Terminus-style terminal agent using claude -p and tmux
type: project
---

Termiclaw is a Python terminal agent that mirrors Terminus-2's architecture: observe-decide-act loop, single tmux pane, raw keystrokes only, three-subagent summarization.

Key decisions made during spec conversation (2026-04-05):
- Planner: stateless `claude -p` calls (no --resume), prompt engineering for JSON output
- One tool only: tmux keystrokes (Terminus spirit)
- Response format mirrors Terminus: analysis, plan, commands[{keystrokes, duration}], task_complete
- Vanilla Python 3.13, zero pip dependencies
- No packaging — `python -m termiclaw run "..."`
- 100ms minimum delay between planner calls
- Double-finish confirmation
- Summarization from the start (three-subagent pipeline)
- ATIF-style JSONL trajectory
- tmux is a system dependency, not bundled
- ~8 file lean architecture
- Eventual Go rewrite planned (distant)

**Why:** User wants to legally use Claude Code subscription (not API) as the LLM backend. `claude -p` subprocess calls are explicitly allowed by Anthropic for personal automation.

**How to apply:** All design decisions should maintain Terminus parity unless there's a strong reason to diverge. Keep it lean.
