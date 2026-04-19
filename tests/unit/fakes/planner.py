"""In-memory `PlannerPort` fake."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from termiclaw.errors import PlannerError
from termiclaw.models import ParseResult, PlannerUsage
from termiclaw.result import Err, Ok

if TYPE_CHECKING:
    from termiclaw.result import Result


@dataclass
class FakePlannerPort:
    """Planner fake. Scripted `query` responses; deterministic parse.

    - `query_responses` is a deque; each `query()` pops one and returns
      it. Empty deque returns `Err(PlannerError("planner fake exhausted"))`.
    - `parse_responses` similarly; empty deque treats the raw as JSON
      `{"result": raw}` and returns `ParseResult()`.
    - `usage_responses` for `extract_usage`; empty returns default.
    - `build_prompt` is deterministic — returns a simple concat.
    """

    query_responses: deque[Result[str, PlannerError]] = field(default_factory=deque)
    parse_responses: deque[Result[ParseResult, PlannerError]] = field(default_factory=deque)
    usage_responses: deque[PlannerUsage] = field(default_factory=deque)
    calls: list[str] = field(default_factory=list)

    def query(  # noqa: PLR0913
        self,
        prompt: str,
        *,
        timeout: int,
        retries: int,
        claude_session_id: str,
        first_call: bool,
        resume_parent: str | None,
        fork_session: bool,
    ) -> Result[str, PlannerError]:
        _ = (timeout, retries, claude_session_id, first_call, resume_parent, fork_session)
        self.calls.append(prompt)
        if self.query_responses:
            return self.query_responses.popleft()
        return Err(PlannerError("planner fake exhausted"))

    def build_prompt(
        self,
        instruction: str,
        observation: str,
        summary: str | None,
        qa_context: str | None,
    ) -> str:
        _ = (summary, qa_context)
        return f"{instruction}\n{observation}"

    def parse_response(self, raw: str) -> Result[ParseResult, PlannerError]:
        _ = raw
        if self.parse_responses:
            return self.parse_responses.popleft()
        return Ok(ParseResult())

    def extract_usage(self, raw: str) -> PlannerUsage:
        _ = raw
        if self.usage_responses:
            return self.usage_responses.popleft()
        return PlannerUsage()
