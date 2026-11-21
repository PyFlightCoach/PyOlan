"""F3A families, group 21 (double Immelmann).

Conventions decided per family (checked against the USG drawings):

- double Immelmann (21): a racetrack in the vertical plane: from the entry line a
  half loop up (the right-hand end), the first roll straight out of it, a line flown
  back the other way, a half loop down (the left-hand end) and the second roll
  straight out of that, onto the exit line in the entry direction at the entry
  height (owner, catalogue review 2026-11-21: "start at dot, pull half loop,
  immediately half roll, draw line, push half loop, immediate half roll"; the rolls
  are not centred on lines). Both half loops are in one sense (counter-clockwise from
  the bottom), of the same radius, so the figure finishes at its entry height. "from
  top" is the mirror image about the entry height (down first, then up). Whether
  each loop is pulled or pushed follows from the attitude: after a pulled half loop
  a half roll makes the second loop a push, a full roll leaves it a pull.
- the rolls: "<rolls>" (plural) is the same roll in both places, "<roll> first,
  <roll> second" gives one to each. A half roll then a full roll exits inverted,
  as the drawings' attitudes say (their entry and exit line styles in 21.3 and
  21.4 look swapped against that).
- the directions of the rolls are the pilot's choice, as everywhere in F3A.
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause, Entry, Exit, Loop, Roll

from .families import Modifiers, _is_plural, _sense, family  # isort: skip

_FIRST_RE = re.compile(r"^(?P<roll>.+?) first$")
_SECOND_RE = re.compile(r"^(?P<roll>.+?) second$")


@family("double immelmann")
def double_immelmann(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    rolls: list[OlanRoll] = []
    for phrase in phrases:
        if rolls and len(rolls) == 2:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
        if not rolls and _is_plural(phrase):
            rolls = [require_roll(phrase)] * 2
        elif not rolls and (match := _FIRST_RE.match(phrase)):
            rolls = [require_roll(match.group("roll"))]
        elif len(rolls) == 1 and (match := _SECOND_RE.match(phrase)):
            rolls.append(require_roll(match.group("roll")))
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
    if len(rolls) != 2:
        raise F3AParseError(f"{name}: expected a roll for each half loop, got {phrases!r}")
    sense = _sense(mods)
    half = Fraction(1, 2)
    return [
        Entry(mods.entry),
        Loop(half, sense=sense),
        Roll(rolls[0], after_loop=True),
        Loop(half, sense=sense),
        Roll(rolls[1], after_loop=True),
        Exit(mods.exit),
    ]
