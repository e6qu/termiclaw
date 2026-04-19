"""Tests for termiclaw.tagging."""

from __future__ import annotations

from termiclaw.tagging import FailureCategory, is_valid_category, valid_categories


def test_valid_categories_contains_all_enum_values():
    cats = valid_categories()
    for c in FailureCategory:
        assert c.value in cats


def test_is_valid_category_accepts_known():
    assert is_valid_category("stuck_loop")
    assert is_valid_category(FailureCategory.PARSE_FAILURE.value)


def test_is_valid_category_rejects_unknown():
    assert not is_valid_category("bogus_category")
    assert not is_valid_category("")
    assert not is_valid_category("STUCK_LOOP")  # case-sensitive


def test_failure_category_string_enum_roundtrip():
    assert FailureCategory("timeout") is FailureCategory.TIMEOUT
    assert str(FailureCategory.HALLUCINATION) == "hallucination"
