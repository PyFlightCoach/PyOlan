"""F3A families, groups 11 (45 degree lines) and 12 (Figure Z).

Conventions decided per family (checked against the USG drawings):

- 45 degree up / down (11): entry line, 1/8 loop onto a 45 degree line, the
  line, 1/8 loop back to level (the other way), exit line. The level lines at
  the ends have no length of their own in the template (the loops are the
  corners), as in the cobra roll. The figure starts high and ends low for
  "down", the other way for "up". The sense of each loop is the travel
  direction, so an inverted entry changes only whether the loops are pulled or
  pushed (the drawings show the whole figure dashed).
- a lone roll or snap ("full snap roll", "1 1/2 snap roll") is centred on the
  45 degree line. "two 2/4 pt rolls reversed" is two such rolls on the line,
  the second the opposite way round to the first (the drawing puts two roll
  symbols one after the other, both centred on the line). It is flown as one
  roll element whose angles are [+a, +a, -a, -a]: the builder's reversible
  rolls give both ways round for the pair, and the figure keeps its attitude.
- Figure Z (12): level entry line, a 3/8 loop up to a 135 degree line (back
  against the direction of flight), the line, a 3/8 loop the other way to level
  and the exit line, which is above the entry line. Both loops are 3/8 and the
  line is the same length whatever the loops, so nothing needs to be closed.
  "from top" is the mirror image about the entry height (down 135 degrees, ending
  below). The roll sits centred on the 135 degree line, and "up" (from bottom) or
  "down" (from top) in its words names that line's direction; the word is checked
  and may be missing ("2/2pt roll" from top).
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import AMOUNT, parse_amount, parse_roll, require_roll, signed
from .steps import Clause, Entry, Exit, Line, Loop, Roll

from .families import Modifiers, _sense, family  # isort: skip

_REVERSED_RE = re.compile(rf"^(?P<count>{AMOUNT}) (?P<roll>.+?) reversed$")


def _line_rolls(name: str, phrases: list[str]) -> list[OlanRoll]:
    """The rolls on the line, in order: a lone roll, or two reversed rolls."""
    if len(phrases) != 1:
        raise F3AParseError(f"{name}: expected one roll phrase, got {phrases!r}")
    phrase = phrases[0]
    if match := _REVERSED_RE.match(phrase):
        if parse_amount(match.group("count")) != 2:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
        roll = require_roll(match.group("roll"))
        return [roll, signed(roll, -1)]
    return [require_roll(phrase)]


def _clauses_with_rolls(
    mods: Modifiers, corners: list[tuple[Fraction, int]], rolls: list[OlanRoll]
) -> list[Clause]:
    """Entry, loop, the one leg with its rolls in order, loop, exit."""
    (first, sense1), (second, sense2) = corners
    theta = (first * sense1) % 1
    return [
        Entry(mods.entry),
        Loop(first, sense=sense1),
        Line(frozenset({theta}), label="leg 1"),
        *[Roll(roll) for roll in rolls],
        Loop(second, sense=sense2),
        Exit(mods.exit),
    ]


def _forty_five(name: str, mods: Modifiers, phrases: list[str], down: bool) -> list[Clause]:
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    rolls = _line_rolls(name, phrases)
    sense = -1 if down else 1
    corners = [(Fraction(1, 8), sense), (Fraction(1, 8), -sense)]
    return _clauses_with_rolls(mods, corners, rolls)


@family("45 degree up")
def forty_five_up(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _forty_five(name, mods, phrases, down=False)


@family("45 degree down")
def forty_five_down(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _forty_five(name, mods, phrases, down=True)


_Z_ROLL_RE = re.compile(r"^(?P<roll>.+?)(?: (?P<way>up|down))?$")


@family("figure z")
def figure_z(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if len(phrases) != 1 or not (match := _Z_ROLL_RE.match(phrases[0])):
        raise F3AParseError(f"{name}: expected one roll, got {phrases!r}")
    way, sense = match.group("way"), _sense(mods)
    if way is not None and way != ("down" if sense == -1 else "up"):
        raise F3AParseError(
            f"{name}: the 135 degree line of a figure Z from {mods.start or 'bottom'} "
            f"goes {'down' if sense == -1 else 'up'}, not {way}"
        )
    roll = parse_roll(match.group("roll"))
    if roll is None:
        raise F3AParseError(f"{name}: not a roll: {match.group('roll')!r}")
    corners = [(Fraction(3, 8), sense), (Fraction(3, 8), -sense)]
    return _clauses_with_rolls(mods, corners, [roll])
