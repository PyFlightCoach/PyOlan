"""F3A families, group 21 (double Immelmann).

Conventions decided per family (checked against the USG drawings):

- double Immelmann (21): a racetrack in the vertical plane, flown the way the
  drawings show it: entry line, a roll, a 1/2 loop up (the right-hand end), a
  line flown back the other way with a second roll, a 1/2 loop down (the
  left-hand end) and the exit line, in the entry direction at the entry height.
  Both half loops are in one sense (counter-clockwise from the bottom), of the
  same radius, so the figure finishes at its entry height. "from top" is the
  mirror image about the entry height (down first, then up).
- the first roll is the one at the start of the figure (so, as for every roll that
  starts a figure, a line follows it) and the second is centred on the line between
  the half loops. The drawings put both arrows at the end of their line, next to
  the loop that follows. Whether each loop is pulled or pushed follows from the
  rolls: a half roll makes the loop after it a push loop, a full roll leaves it
  a pull loop.
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
        Roll(rolls[0]),
        Loop(half, sense=sense),
        Roll(rolls[1]),
        Loop(half, sense=sense),
        Exit(mods.exit),
    ]
