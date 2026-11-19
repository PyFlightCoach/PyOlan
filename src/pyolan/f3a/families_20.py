"""F3A families, group 20 (stall turn).

Conventions decided per family (checked against the USG drawings):

- stall turn (20): entry, 1/4 loop up, a vertical upline with its roll, the stall
  turn, a vertical downline with its roll and a 1/4 loop out in the entry direction
  (the drawings show the exit line continuing the entry line's way, a "centre"
  figure). The description gives one roll for each line as ``<roll> up`` and
  ``<roll> down``, in either order; both lines must be rolled and are rolled at
  their centre.
- the figure does not finish at its entry height, by definition: the drawings enter
  at the middle of the vertical and leave at its bottom (USG height "middle" to
  "low"). The template rises as far above the entry as it ends below it, so the
  entry is exactly at mid height: the upline is ``UP_LINE`` (one length long enough
  for any of the rolls and their pads, as in Figure M) and the downline ``DOWN_LINE``,
  twice the climb (loop radius and upline) less the loop radius that it still has to
  fly after the downline.
- exit attitude: the drawings leave upright unless the text says ``inverted exit``
  (also after an ``inverted entry``). The rolls on the two lines are linked in one
  mirror ``roll_option`` (the figure as drawn or its mirror): whether the two quarter
  turn rolls go the same way or opposite ways decides the exit attitude (steps.py
  picks the relative directions that give it), so only both together can be
  mirrored.
"""

from __future__ import annotations

import re

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import DOWN_LINE, UP, Clause, Entry, Exit, Line, Roll, StallTurn

from .families import Modifiers, family  # isort: skip

# A 3/4pt roll and its pads are 170 m at the default parameters, line_length is 130 m
UP_LINE = "(1.5*line_length)"
# the figure ends as far below the entry as its top is above it: the up line and
# the loop before it climb UP_LINE + loop_radius, the down line and the loop after
# it drop twice that
DOWN_LINE_LENGTH = "((3*line_length)+loop_radius)"

_UPDOWN_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")


@family("stall turn")
def stall_turn(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    exit_attitude = mods.exit
    found: dict[str, OlanRoll] = {}
    for phrase in phrases:
        if phrase == "inverted exit":
            if exit_attitude is not None:
                raise F3AParseError(f"{name}: the exit attitude is given twice")
            exit_attitude = p.Orientation.INVERTED
            continue
        match = _UPDOWN_RE.match(phrase)
        if not match or match.group("dir") in found:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
        found[match.group("dir")] = require_roll(match.group("roll"))
    if set(found) != {"up", "down"}:
        raise F3AParseError(f"{name}: expected a roll up and a roll down, got {phrases!r}")
    return [
        Entry(mods.entry),
        Line(UP, length=UP_LINE),
        Roll(found["up"]),
        StallTurn(),
        Line(DOWN_LINE, length=DOWN_LINE_LENGTH),
        Roll(found["down"]),
        Exit(exit_attitude if exit_attitude is not None else p.Orientation.UPRIGHT),
    ]
