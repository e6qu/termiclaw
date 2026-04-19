# Contributing

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- [Docker](https://docs.docker.com/get-docker/) (daemon running — tmux runs inside the container, not on the host)
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
| pre-commit | no-object-signatures | Forbids `object` / `Any` in type annotations outside the boundary allowlist |
| pre-commit | no-monkeypatch | Forbids pytest's `monkeypatch` fixture — refactor for real injection seams instead |
| pre-commit | exhaustive-match | Forbids `case _:` in `termiclaw/decide.py` and `shell.py` (the sum-type dispatch cores) |
| pre-commit | no-reserved-logrecord-keys | Forbids reserved `LogRecord` attribute names (`name`, `msg`, `args`, …) as keys in `extra=` dicts — collision crashes the logger (BUG-33) |
| pre-commit | no-shlex-quote-in-argv | Forbids `shlex.quote(…)` under `termiclaw/` without `# shlex-quote-ok` — subprocess list-mode bypasses the shell so quoting injects literal quotes into the callee (BUG-15/42) |
| commit-msg | conventional-pre-commit | Conventional commit format |
| pre-push | pytest-unit | Unit tests with coverage |
| pre-push | pytest-integration | Integration tests (requires Docker) |
| pre-push | update-loc-badges | Updates code/test LOC badges in README |

## Running tests

```bash
# Unit tests
uv run pytest tests/unit/

# Integration tests (requires Docker)
uv run pytest tests/integration/ -m docker

# With coverage
uv run pytest tests/unit/ --cov=termiclaw --cov-branch --cov-fail-under=84
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

See [docs/DESIGN.md](docs/DESIGN.md) for the architectural comparison against Terminus; source in `termiclaw/` is authoritative.

```
termiclaw/
  cli.py              argparse, startup checks, subcommand dispatch
  agent.py            top-level run() — thin shell over decide + apply
  decide.py           pure decision core (Event → Transition)
  shell.py            apply(cmd, ports) — dispatches side effects
  ports.py            Protocols for container, planner, persistence, artifacts, summarize
  runtime.py          default Ports impls (wraps container/db/planner/etc.)
  state.py            frozen State, ForkContext, StallState, helpers
  commands.py         Command sum type
  events.py           Event sum type
  transitions.py      Transition product type
  agent_core.py       pure decision helpers (stall policy, formatters)
  container.py        docker + tmux subprocess layer
  planner.py          claude -p invocation + JSON parsing
  summarizer.py       three-subagent summarization
  summarize_worker.py async background wrapper
  artifacts.py        STATUS/DO_NEXT/WHAT_WE_DID/PLAN markdown refresh
  db.py               SQLite: runs, steps, MCTS, failure tags
  trajectory.py       JSONL trajectory log
  atif.py             ATIF v1.6 export
  mcts.py             Monte-Carlo Tree Search over forks
  verifier.py         task verifier (bash exit-code)
  tagging.py          FailureCategory enum
  task_file.py        TOML task loader
  validate.py         JSON boundary validators (Result[T, ParseError])
  errors.py           TermiclawError hierarchy
  result.py           Ok[T] | Err[E]
  models.py           Config, ParsedCommand, ParseResult, StepRecord, RunInfo, PlannerUsage
  stall.py            stall detection (pure)
  logging.py          JSON structured logger
```

Zero runtime dependencies. Dev: pytest, pytest-cov, ruff, ty, pre-commit.
