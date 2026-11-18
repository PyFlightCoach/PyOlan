"""F3A families, groups 07 (six sided loop), 08 (cobra roll) and 09 (golf ball).

Conventions decided per family (checked against the USG drawings):

- six sided loop (07): a regular hexagon flown as six 1/6 loops joined by five
  equal lines, all turning one way. The entry and exit lines are the base
  of the hexagon (the drawing draws them over the first and last side), so the
  figure starts and ends at the height of its base. It starts at the bottom of
  the hexagon (loops go up) unless ``from top`` (loops go down). No rolls.
- cobra roll (08): entry line, 1/8 loop to a 45 degree leg, the leg, a 1/4 loop
  over the apex (the other way), the second 45 degree leg and a 1/8 loop back to
  level. The rolls are plural: one in each 45 degree leg (centred, as the
  drawings put them), so ``2/4pt rolls`` leave the apex inverted and
  ``2/2pt rolls`` do not. ``from top`` is the same shape upside down (a V).
- golf ball (09): entry line, 1/8 loop to a 45 degree upline, the upline,
  a 3/4 loop in the same sense, a 45 degree downline crossing the upline and
  a 1/8 loop back to level; the loops go up (counter-clockwise when flying left
  to right) whatever the entry attitude, as the drawings show for the inverted
  entries too. The words in brackets ("45 degrees up, 3/4 inside loop,
  45 degrees down, pull to level") are checked against that shape. Plural rolls
  go one on the upline and one on the downline.
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .families import Modifiers, _is_plural, _sense, family
from .rolls import require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll


def _legs(
    mods: Modifiers,
    corners: list[tuple[Fraction, int]],
    rolls: dict[int, OlanRoll],
) -> list[Clause]:
    """Loops (amount, sense) joined by lines; rolls by leg number from 1.

    The first leg follows the first loop. The figure starts on the entry line
    and ends on the exit line, so every corner is a loop.
    """
    clauses: list[Clause] = [Entry(mods.entry)]
    theta = Fraction(0)
    for i, (amount, sense) in enumerate(corners, start=1):
        clauses.append(Loop(amount, sense=sense))
        theta = (theta + amount * sense) % 1
        if i < len(corners):
            clauses.append(Line(frozenset({theta}), label=f"leg {i}"))
            if i in rolls:
                clauses.append(Roll(rolls[i]))
    clauses.append(Exit(mods.exit))
    return clauses


@family("six sided loop")
def six_sided_loop(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if phrases:
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    sense = _sense(mods)
    return _legs(mods, [(Fraction(1, 6), sense)] * 6, {})


def _plural_roll(name: str, phrases: list[str]) -> OlanRoll | None:
    """The one roll phrase (plural: one in each of two legs), or None."""
    if not phrases:
        return None
    if len(phrases) != 1 or not _is_plural(phrases[0]):
        raise F3AParseError(f"{name}: expected one plural roll, got {phrases!r}")
    return require_roll(phrases[0])


@family("cobra roll")
def cobra_roll(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    roll = _plural_roll(name, phrases)
    if roll is None:
        raise F3AParseError(f"{name}: the rolls are missing")
    sense = _sense(mods)
    corners = [(Fraction(1, 8), sense), (Fraction(1, 4), -sense), (Fraction(1, 8), sense)]
    return _legs(mods, corners, {1: roll, 2: roll})


_GOLF_BALL_RE = re.compile(
    r"^\(45 degree up, 3/4 inside loop, 45 degree down, pull to level\)$"
)


@family("golf ball")
def golf_ball(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    if phrases and phrases[0].startswith("("):
        # the shape in words: its commas split it into phrases
        end = next((i for i, ph in enumerate(phrases) if ph.endswith(")")), len(phrases) - 1)
        shape = ", ".join(phrases[: end + 1])
        if not _GOLF_BALL_RE.match(shape):
            raise F3AParseError(f"{name}: unexpected {shape!r}")
        if mods.entry != mods.entry.UPRIGHT:
            raise F3AParseError(
                f"{name}: an inside loop with an inverted entry would go down, not up"
            )
        phrases = phrases[end + 1 :]
    roll = _plural_roll(name, phrases)
    corners = [(Fraction(1, 8), 1), (Fraction(3, 4), 1), (Fraction(1, 8), 1)]
    return _legs(mods, corners, {1: roll, 2: roll} if roll is not None else {})
