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
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

## Pre-commit hooks

Installed automatically by `pre-commit install`:

| Stage | Hook | What it does |
|-------|------|-------------|
| pre-commit | trailing-whitespace, end-of-file-fixer | Whitespace cleanup |
| pre-commit | check-yaml, check-json, check-toml | Config file validation |
| pre-commit | check-branch | Blocks commits on `main`, requires rebase on `origin/main` |
| pre-commit | ruff, ruff-format | Lint and auto-format |
| pre-commit | ty-check | Type checking |
| commit-msg | conventional-pre-commit | Conventional commit format |
| pre-push | pytest-unit | Unit tests with coverage |

## Running tests

```bash
# Unit tests
uv run pytest

# Integration tests (requires tmux)
uv run pytest tests/integration/ -m integration

# With coverage
uv run pytest --cov=termiclaw --cov-branch
```

## Linting and type checking

All enforced by pre-commit, but can be run manually:

```bash
uv run ruff check .       # lint
uv run ruff format .      # auto-format
uv run ty check           # type check
```

## Conventional commits

Commit messages must follow [Conventional Commits](https://www.conventionalcommits.org/) (enforced by pre-commit and CI):

```
feat: add replay command
fix: handle empty terminal output
docs: update README
chore: bump ruff
```

`feat:` = minor bump, `fix:` = patch bump, `BREAKING CHANGE:` in body = major bump. Releases are automated by [release-please](https://github.com/googleapis/release-please).

## Pull request process

1. Create a branch from `main` (never commit directly to `main`)
2. Make changes, let pre-commit hooks run
3. Push (pre-push runs unit tests)
4. Open a PR against `main`

## Architecture

See [SPEC.md](SPEC.md) for the full specification.

```
termiclaw/
  cli.py            argparse, startup checks, list/show/status
  agent.py          observe-decide-act loop
  planner.py        claude -p invocation, JSON parsing, auto-fix
  tmux.py           tmux subprocess wrapper
  models.py         dataclasses (Config, RunState, ParseResult, etc.)
  summarizer.py     three-subagent pipeline
  trajectory.py     JSONL logging, run listing
  logging.py        structured JSON formatter
```

Zero runtime dependencies. Dev: pytest, pytest-cov, ruff, ty, pre-commit.
