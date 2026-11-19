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
from .rolls import is_quarter, require_roll
from .steps import DOWN_LINE, UP, Clause, Entry, Exit, Line, Roll, StallTurn

from .families import Modifiers, family  # isort: skip

# A 3/4pt roll and its pads are 170 m at the default parameters, line_length is 130 m
UP_LINE = "(1.5*line_length)"
# the figure ends as far below the entry as its top is above it: the up line and
# the loop before it climb UP_LINE + loop_radius, the down line and the loop after
# it drop twice that
DOWN_LINE_LENGTH = "((3*line_length)+loop_radius)"

_UPDOWN_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")


_BOTH_RE = re.compile(r"^(?P<first>.+? (?:up|down)) (?P<second>.+? (?:up|down))$")


def _split_missing_comma(phrases: list[str]) -> list[str]:
    """H.14 has no comma between its two rolls: '3/4pt roll up 1/4 roll down'."""
    result: list[str] = []
    for phrase in phrases:
        if match := _BOTH_RE.match(phrase):
            result += [match.group("first"), match.group("second")]
        else:
            result.append(phrase)
    return result


def _default_exit(mods: Modifiers, found: dict[str, OlanRoll]) -> p.Orientation:
    """The exit attitude when the text does not state one.

    A centre figure (group 20) leaves upright. A turnaround (lettered groups, see
    families_g_h) with rolls of whole half turns leaves in the entry attitude after
    an even number of half rolls in all and in the other one after an odd number
    (the stall turn and the turnaround loop add nothing, as the drawings show). With
    quarter rolls (3/4 and 1/4, or a 3/4 and a 1 1/4 snap) the directions of the two
    are the pilot's choice and decide the attitude, so the drawings' upright exit
    is used for either entry, as in group 20.
    """
    if mods.forward:
        return p.Orientation.UPRIGHT
    if any(is_quarter(roll) for roll in found.values()):
        return p.Orientation.UPRIGHT
    half_rolls = round(2 * sum(abs(roll.total()) for roll in found.values()))
    if half_rolls % 2 == 0:
        return mods.entry
    return p.Orientation.UPRIGHT if mods.entry == p.Orientation.INVERTED else p.Orientation.INVERTED


@family("stall turn")
def stall_turn(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    exit_attitude = mods.exit
    found: dict[str, OlanRoll] = {}
    for phrase in _split_missing_comma(phrases):
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
    if exit_attitude is None:
        exit_attitude = _default_exit(mods, found)
    return [
        Entry(mods.entry),
        Line(UP, length=UP_LINE),
        Roll(found["up"]),
        StallTurn(),
        Line(DOWN_LINE, length=DOWN_LINE_LENGTH),
        Roll(found["down"]),
        Exit(exit_attitude),
    ]
