"""Result type: Ok[T] | Err[E] for functions that can fail.

Expected failures flow through `Result`; exceptions are reserved for
programmer errors (violated invariants). Callers narrow via
`match result: case Ok(x): ...; case Err(e): ...` or `isinstance`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class Ok[T]:
    """Success carrier."""

    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self.value

    def map[U](self, fn: Callable[[T], U]) -> Ok[U]:
        return Ok(fn(self.value))


@dataclass(frozen=True, slots=True)
class Err[E]:
    """Failure carrier."""

    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> NoReturn:
        msg = f"called unwrap on Err: {self.error!r}"
        raise RuntimeError(msg)

    def map[U, T](self, _fn: Callable[[T], U]) -> Err[E]:
        """Propagate Err through a map chain (identity on Err, like Rust)."""
        return self


type Result[T, E] = Ok[T] | Err[E]
