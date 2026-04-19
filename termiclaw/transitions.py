"""Transition: the product type returned by `decide`.

Pairs a new `State` with the commands the imperative shell should
apply next. Kept as a named product so call sites and logs can
inspect it structurally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from termiclaw.commands import Command
    from termiclaw.state import State


@dataclass(frozen=True, slots=True)
class Transition:
    """A `decide` result: next state + commands to apply."""

    state: State
    commands: tuple[Command, ...] = ()
