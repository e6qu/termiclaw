"""Tests for termiclaw.verifier."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from termiclaw.result import Err, Ok
from termiclaw.verifier import VerifierResult, VerifierSpec, reward_from_result, verify


def test_verifier_spec_defaults():
    spec = VerifierSpec(command="echo hi")
    assert spec.expected_exit == 0
    assert spec.expected_output_pattern is None
    assert spec.timeout_seconds == 30.0


def test_verifier_spec_frozen():
    spec = VerifierSpec(command="echo hi")
    with pytest.raises(AttributeError):
        setattr(spec, "command", "ls")  # noqa: B010


def test_reward_from_result_passed():
    r = VerifierResult(
        passed=True,
        actual_exit=0,
        actual_output="",
        elapsed_seconds=0.1,
        reason="pass",
    )
    assert reward_from_result(r) == 1.0


def test_reward_from_result_failed():
    r = VerifierResult(
        passed=False,
        actual_exit=1,
        actual_output="",
        elapsed_seconds=0.1,
        reason="exit_mismatch",
    )
    assert reward_from_result(r) == 0.0


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_verify_pass():
    with patch("termiclaw.verifier.subprocess.run", return_value=_completed(0, "ok")):
        result = verify("cid", VerifierSpec(command="true"))
    assert isinstance(result, Ok)
    assert result.value.passed is True
    assert result.value.reason == "pass"


def test_verify_exit_mismatch():
    with patch("termiclaw.verifier.subprocess.run", return_value=_completed(1)):
        result = verify("cid", VerifierSpec(command="false"))
    assert isinstance(result, Ok)
    assert result.value.passed is False
    assert result.value.reason == "exit_mismatch"


def test_verify_pattern_mismatch():
    with patch("termiclaw.verifier.subprocess.run", return_value=_completed(0, "nope")):
        result = verify(
            "cid",
            VerifierSpec(command="echo", expected_output_pattern=r"^yes$"),
        )
    assert isinstance(result, Ok)
    assert result.value.passed is False
    assert result.value.reason == "pattern_mismatch"


def test_verify_pattern_match():
    with patch("termiclaw.verifier.subprocess.run", return_value=_completed(0, "yes\n")):
        result = verify(
            "cid",
            VerifierSpec(command="echo", expected_output_pattern=r"^yes$"),
        )
    assert isinstance(result, Ok)
    assert result.value.passed is True


def test_verify_timeout():
    err = subprocess.TimeoutExpired(cmd=["docker"], timeout=1.0)
    with patch("termiclaw.verifier.subprocess.run", side_effect=err):
        result = verify("cid", VerifierSpec(command="sleep 100"))
    assert isinstance(result, Ok)
    assert result.value.passed is False
    assert result.value.reason == "timeout"


def test_verify_docker_missing():
    with patch("termiclaw.verifier.subprocess.run", side_effect=FileNotFoundError):
        result = verify("cid", VerifierSpec(command="true"))
    assert isinstance(result, Err)


def test_verify_invalid_regex():
    with patch("termiclaw.verifier.subprocess.run", return_value=_completed(0, "ok")):
        result = verify(
            "cid",
            VerifierSpec(command="echo", expected_output_pattern="["),
        )
    assert isinstance(result, Err)
