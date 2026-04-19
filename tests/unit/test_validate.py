"""Tests for termiclaw.validate."""

from __future__ import annotations

from termiclaw.result import Err, Ok
from termiclaw.validate import (
    optional_bool,
    optional_float,
    optional_list,
    optional_str,
    require_dict,
    require_json_object,
    required_bool,
    required_int,
    required_list,
    required_str,
)


def test_require_json_object_valid():
    result = require_json_object('{"x": 1}')
    assert isinstance(result, Ok)
    assert result.unwrap() == {"x": 1}


def test_require_json_object_not_json():
    result = require_json_object("not json")
    assert isinstance(result, Err)
    assert result.error.field == "<root>"


def test_require_json_object_not_dict():
    result = require_json_object("[1, 2]")
    assert isinstance(result, Err)


def test_required_str_present():
    assert required_str({"k": "v"}, "k") == Ok("v")


def test_required_str_missing():
    assert isinstance(required_str({}, "k"), Err)


def test_required_str_wrong_type():
    assert isinstance(required_str({"k": 123}, "k"), Err)


def test_optional_str_missing_returns_default():
    assert optional_str({}, "k", default="x") == Ok("x")


def test_optional_str_wrong_type_is_err():
    assert isinstance(optional_str({"k": 123}, "k"), Err)


def test_required_bool_present():
    result = required_bool({"k": True}, "k")
    assert isinstance(result, Ok)
    assert result.value is True


def test_required_bool_wrong_type():
    assert isinstance(required_bool({"k": "true"}, "k"), Err)


def test_required_bool_rejects_int():
    """In Python, `isinstance(True, int)` is True but we want strict bool check."""
    assert required_bool({"k": 1}, "k").is_err()


def test_optional_bool_missing():
    result = optional_bool({}, "k", default=False)
    assert isinstance(result, Ok)
    assert result.value is False


def test_optional_float_missing():
    assert optional_float({}, "k", default=1.5) == Ok(1.5)


def test_optional_float_accepts_int():
    assert optional_float({"k": 3}, "k", default=0.0) == Ok(3.0)


def test_optional_float_accepts_float():
    assert optional_float({"k": 3.14}, "k", default=0.0) == Ok(3.14)


def test_optional_float_rejects_bool():
    assert isinstance(optional_float({"k": True}, "k", default=0.0), Err)


def test_optional_float_rejects_string():
    assert isinstance(optional_float({"k": "3.14"}, "k", default=0.0), Err)


def test_required_int_present():
    assert required_int({"k": 5}, "k") == Ok(5)


def test_required_int_rejects_bool():
    assert isinstance(required_int({"k": True}, "k"), Err)


def test_required_int_rejects_float():
    assert isinstance(required_int({"k": 1.5}, "k"), Err)


def test_required_list_present():
    assert required_list({"k": [1, "x"]}, "k") == Ok([1, "x"])


def test_required_list_missing():
    assert isinstance(required_list({}, "k"), Err)


def test_required_list_wrong_type():
    assert isinstance(required_list({"k": "x"}, "k"), Err)


def test_optional_list_missing_returns_empty():
    assert optional_list({}, "k") == Ok([])


def test_require_dict_narrow_from_object():
    assert require_dict({"k": 1}, "field") == Ok({"k": 1})


def test_require_dict_wrong_type():
    assert isinstance(require_dict([], "field"), Err)
