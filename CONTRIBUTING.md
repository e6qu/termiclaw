# Contributing

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- [tmux](https://github.com/tmux/tmux) (for integration tests)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (for end-to-end testing)

## Setup

```bash
git clone https://github.com/e6qu/termiclaw.git
cd termiclaw
uv sync --all-groups
```

## Running tests

```bash
# Unit tests (no external deps needed)
uv run pytest

# Integration tests (requires tmux)
uv run pytest tests/integration/ -m integration

# With verbose output
uv run pytest -v
```

## Linting and type checking

All three must pass before committing:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

To auto-fix formatting:

```bash
uv run ruff format .
```

## Conventional commits

This project uses [release-please](https://github.com/googleapis/release-please) for automated releases. Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add replay command
fix: handle empty terminal output in incremental diff
docs: update README with new CLI flags
chore: bump ruff to 0.12
```

- `feat:` triggers a minor version bump
- `fix:` triggers a patch version bump
- `BREAKING CHANGE:` in the commit body triggers a major version bump

## Pull request process

1. Fork the repo and create a branch
2. Make your changes
3. Ensure `ruff check`, `ruff format --check`, `ty check`, and `pytest` all pass
4. Write tests for new functionality
5. Use conventional commit messages
6. Open a PR against `main`

## Architecture

See [SPEC.md](SPEC.md) for the full specification and [TERMINUS.md](TERMINUS.md) for the Terminus-2 reference.

```
termiclaw/
  cli.py            argparse, startup checks
  agent.py          observe-decide-act loop
  planner.py        claude -p invocation, JSON parsing
  tmux.py           tmux subprocess wrapper
  models.py         dataclasses
  summarizer.py     three-subagent pipeline
  trajectory.py     JSONL logging
  logging.py        structured JSON formatter
```

Zero runtime dependencies. Dev dependencies: pytest, pytest-cov, ruff, ty.
