"""Task verifier: run a shell command inside the container, score pass/fail.

`VerifierSpec` is the task-defined success condition. `verify()` runs it
against a live container and returns `VerifierResult` wrapped in Result.
Used by `termiclaw eval` for scoring and by `termiclaw mcts` for rewards.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from termiclaw.errors import ContainerError
from termiclaw.logging import get_logger
from termiclaw.result import Err, Ok

if TYPE_CHECKING:
    from termiclaw.result import Result

_log = get_logger("verifier")


@dataclass(frozen=True, slots=True)
class VerifierSpec:
    """Task-defined success criterion.

    After the agent declares `task_complete=true`, the orchestrator runs
    `command` inside the container. The task passes iff the exit code
    matches `expected_exit` AND the stdout matches `expected_output_pattern`.
    """

    command: str
    expected_exit: int = 0
    expected_output_pattern: str | None = None
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class VerifierResult:
    """Outcome of running a VerifierSpec."""

    passed: bool
    actual_exit: int
    actual_output: str
    elapsed_seconds: float
    reason: str  # "pass" | "exit_mismatch" | "pattern_mismatch" | "timeout" | "error"


def verify(
    container_id: str,
    spec: VerifierSpec,
) -> Result[VerifierResult, ContainerError]:
    """Run the verifier inside the container, return pass/fail with detail."""
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["docker", "exec", container_id, "bash", "-c", spec.command],
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return Ok(
            VerifierResult(
                passed=False,
                actual_exit=-1,
                actual_output="",
                elapsed_seconds=elapsed,
                reason="timeout",
            ),
        )
    except FileNotFoundError:
        return Err(ContainerError("docker binary not found"))

    elapsed = time.monotonic() - start
    output = result.stdout
    if result.returncode != spec.expected_exit:
        return Ok(
            VerifierResult(
                passed=False,
                actual_exit=result.returncode,
                actual_output=output,
                elapsed_seconds=elapsed,
                reason="exit_mismatch",
            ),
        )
    if spec.expected_output_pattern is not None:
        try:
            pattern = re.compile(spec.expected_output_pattern, re.MULTILINE)
        except re.error as e:
            return Err(ContainerError(f"invalid verifier regex: {e}"))
        if not pattern.search(output):
            return Ok(
                VerifierResult(
                    passed=False,
                    actual_exit=result.returncode,
                    actual_output=output,
                    elapsed_seconds=elapsed,
                    reason="pattern_mismatch",
                ),
            )
    _log.info("Verifier passed", extra={"elapsed_s": elapsed})
    return Ok(
        VerifierResult(
            passed=True,
            actual_exit=result.returncode,
            actual_output=output,
            elapsed_seconds=elapsed,
            reason="pass",
        ),
    )


def reward_from_result(result: VerifierResult) -> float:
    """Map a VerifierResult to a scalar reward in [0, 1] for MCTS."""
    return 1.0 if result.passed else 0.0
