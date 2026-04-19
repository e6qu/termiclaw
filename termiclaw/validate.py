"""JSON-schema-adjacent validator combinators.

Input type is `dict[str, object]` (this is the one module where `object`
is allowed — it is the boundary layer). Output type is
`Result[T, ParseError]`. Callers compose via pattern-matching:

    match (required_str(d, "a"), optional_float(d, "b", 0.0)):
        case (Ok(a), Ok(b)):
            ...
        case (Err(e), _) | (_, Err(e)):
            return Err(e)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from termiclaw.errors import ParseError
from termiclaw.result import Err, Ok

if TYPE_CHECKING:
    from termiclaw.result import Result


def require_json_object(text: str) -> Result[dict[str, object], ParseError]:
    """Parse a JSON string and require the top-level value to be an object."""
    try:
        decoded = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return Err(ParseError("<root>", f"invalid JSON: {e}", text[:500]))
    return require_dict(decoded, "<root>", raw=text)


def require_dict(
    value: object,
    field: str,
    *,
    raw: str = "",
) -> Result[dict[str, object], ParseError]:
    """Narrow an arbitrary object to `dict[str, object]`."""
    if not isinstance(value, dict):
        return Err(
            ParseError(field, f"expected object, got {type(value).__name__}", raw or repr(value)),
        )
    return Ok({str(k): v for k, v in value.items()})


def required_str(d: dict[str, object], field: str) -> Result[str, ParseError]:
    """Extract a required string-typed field."""
    if field not in d:
        return Err(ParseError(field, "missing required field", repr(d)))
    value = d[field]
    if not isinstance(value, str):
        return Err(
            ParseError(field, f"expected string, got {type(value).__name__}", repr(d)),
        )
    return Ok(value)


def optional_str(
    d: dict[str, object],
    field: str,
    default: str = "",
) -> Result[str, ParseError]:
    """Extract an optional string-typed field with a default."""
    if field not in d:
        return Ok(default)
    value = d[field]
    if not isinstance(value, str):
        return Err(
            ParseError(field, f"expected string, got {type(value).__name__}", repr(d)),
        )
    return Ok(value)


def required_bool(d: dict[str, object], field: str) -> Result[bool, ParseError]:
    """Extract a required bool-typed field."""
    if field not in d:
        return Err(ParseError(field, "missing required field", repr(d)))
    value = d[field]
    if not isinstance(value, bool):
        return Err(
            ParseError(field, f"expected bool, got {type(value).__name__}", repr(d)),
        )
    return Ok(value)


def optional_bool(
    d: dict[str, object],
    field: str,
    default: bool,  # noqa: FBT001 — default IS the defaultable value
) -> Result[bool, ParseError]:
    """Extract an optional bool-typed field with a default."""
    if field not in d:
        return Ok(default)
    value = d[field]
    if not isinstance(value, bool):
        return Err(
            ParseError(field, f"expected bool, got {type(value).__name__}", repr(d)),
        )
    return Ok(value)


def optional_float(
    d: dict[str, object],
    field: str,
    default: float,
) -> Result[float, ParseError]:
    """Extract an optional numeric field with a default. Accepts int or float."""
    if field not in d:
        return Ok(default)
    value = d[field]
    if isinstance(value, bool):
        return Err(
            ParseError(field, "expected number, got bool", repr(d)),
        )
    if isinstance(value, (int, float)):
        return Ok(float(value))
    return Err(
        ParseError(field, f"expected number, got {type(value).__name__}", repr(d)),
    )


def required_int(d: dict[str, object], field: str) -> Result[int, ParseError]:
    """Extract a required int-typed field (reject bools and floats)."""
    if field not in d:
        return Err(ParseError(field, "missing required field", repr(d)))
    value = d[field]
    if isinstance(value, bool) or not isinstance(value, int):
        return Err(
            ParseError(field, f"expected int, got {type(value).__name__}", repr(d)),
        )
    return Ok(value)


def required_list(d: dict[str, object], field: str) -> Result[list[object], ParseError]:
    """Extract a required list field (elements stay typed as `object`)."""
    if field not in d:
        return Err(ParseError(field, "missing required field", repr(d)))
    value = d[field]
    if not isinstance(value, list):
        return Err(
            ParseError(field, f"expected list, got {type(value).__name__}", repr(d)),
        )
    typed: list[object] = [*value]
    return Ok(typed)


def optional_list(
    d: dict[str, object],
    field: str,
) -> Result[list[object], ParseError]:
    """Extract an optional list field; missing returns an empty list."""
    if field not in d:
        empty: list[object] = []
        return Ok(empty)
    value = d[field]
    if not isinstance(value, list):
        return Err(
            ParseError(field, f"expected list, got {type(value).__name__}", repr(d)),
        )
    typed: list[object] = [*value]
    return Ok(typed)
