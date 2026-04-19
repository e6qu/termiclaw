"""Tests for termiclaw.result."""

from __future__ import annotations

import pytest

from termiclaw.result import Err, Ok


def test_ok_unwrap_returns_value():
    assert Ok(42).unwrap() == 42


def test_ok_is_ok_true():
    assert Ok("hello").is_ok() is True
    assert Ok("hello").is_err() is False


def test_err_is_err_true():
    assert Err("boom").is_err() is True
    assert Err("boom").is_ok() is False


def test_err_unwrap_raises():
    with pytest.raises(RuntimeError, match="Err"):
        Err(ValueError("nope")).unwrap()


def test_ok_map_transforms():
    mapped = Ok(3).map(lambda x: x * 2)
    assert mapped.unwrap() == 6


def test_err_map_is_identity():
    original = Err("boom")
    mapped = original.map(lambda x: x)
    assert mapped is original


def test_ok_err_are_frozen():
    with pytest.raises(AttributeError):
        setattr(Ok(1), "value", 2)  # noqa: B010
    with pytest.raises(AttributeError):
        setattr(Err("x"), "error", "y")  # noqa: B010


def test_ok_err_are_hashable():
    hash(Ok(1))
    hash(Err("boom"))
