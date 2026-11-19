"""F3A families, groups 15 (square eights) and 16 (Figure M).

Conventions decided per family (checked against the USG drawings):

- square horizontal eight (15.1-15.4): two squares side by side in the vertical
  plane, as the drawings show them. Entry line, a 3/4 square loop in one sense
  (1/4, 1/4, 1/4: up, back over the top, down), then the other sense for four
  corners (to the left along the base, up, over the top, down), and a last 1/4
  corner to the exit line. Corners are +1/4 x3, -1/4 x4, +1/4 and all seven
  lines are the same length (one shared ``line_length``). The drawings draw the
  base and the downs of the two squares on top of each other and offset them
  to show it; the template simply flies them. "from top" is the mirror image
  about the entry height (squares hang down). No rolls.
- square vertical eight (15.5-15.16): two squares one above the other, the
  middle line (the "waist") being flown twice, both times in the same direction.
  From the bottom (or top, the mirror image): 1/4 up, 1/4 onto the waist (flown
  back against the entry direction), then the other square the other way for
  four corners (the second pass of the waist is its last leg, flown the same
  way), and 1/4, 1/4 down to the exit line. Corners +1/4, +1/4, -1/4 x4,
  +1/4, +1/4. From the middle (entry on the waist level, the upper square first,
  "bottom first" the mirror): a full 1/4 x4 square, a line (the waist, flown in
  the entry direction) and a full -1/4 x4 square in the other sense. Without
  rolls the figure is flown upright (or inverted) throughout; the loops follow.
- square vertical eight rolls: a half roll sits centred on each pass of the
  waist ("with half rolls", plural, from the bottom or the top), as the arrows
  of the drawings cross both waist lines; from the middle a single "half roll" is
  centred on the waist line between the two squares. Rolls are on lines (the
  waist is a line here), not integrated into loops as in the round vertical
  eight. A half roll on the middle line leaves the figure inverted at exit.
- Figure M (16): entry, 1/4 loop up, vertical up line, stall turn, vertical down
  line, a pushed (negative) half loop towards the figure's direction of travel,
  vertical up line, stall turn, vertical down line, and a 1/4 loop to the exit
  line. The slanted tick at the top of each vertical in the drawings is the
  stall turn symbol, as in group 26. "Centre half-loop is always flown
  negative (inverted)" (16.1): the drawings show the half loop dashed in every
  entry of the group, so all of 16.1-16.6 have it pushed. The figure exits
  in its entry attitude. A vertical's rolls are on both lines ("3/4 rolls",
  "3/4 pt rolls": on the up and the down line of each vertical, four rolls in
  all). "3/4pt rolls up, 1/4 rolls down" are the rolls on the up and the down
  lines as the words say.
  When the up and down rolls differ ("3/4pt rolls up, 1/4 rolls down") all four
  vertical lines are ``(1.5*line_length)`` (builder expression): a 3/4pt roll and
  its pads are longer than ``line_length`` and the 1/4 roll's are not, so the
  default lines would leave the figure above its entry height.
  The signs of the quarter-turn rolls are chosen so that the half loop is a push
  (Loop with both sense and pull, steps.py) and the figure exits in its
  entry attitude. Within a vertical the up and down rolls are linked (the other
  combinations leave the figure in the wrong attitude); each vertical is its own
  mirror option (``roll_option`` and ``roll_option_2``), so the pilot chooses the
  direction of each independently (decided 2026-11-19).
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import DOWN_LINE, UP, Clause, Entry, Exit, Line, Loop, Roll, StallTurn

from .families import Modifiers, _is_plural, _polygon, _sense, family  # isort: skip

Q = Fraction(1, 4)


@family("square horizontal eight")
def square_horizontal_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if phrases:
        raise F3AParseError(f"{name}: unexpected {phrases[0]!r}")
    return _polygon(mods, _sense(mods), [Q, Q, Q, -Q, -Q, -Q, -Q, Q], {})


@family("square vertical eight", entry_heights=True)
def square_vertical_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    middle = mods.start == "middle"
    if mods.entry_form and not middle:
        raise F3AParseError(f"{name}: unexpected the {mods.start} entry")
    if len(phrases) > 1:
        raise F3AParseError(f"{name}: unexpected {phrases[1]!r}")
    phrase = phrases[0] if phrases else None
    if middle:
        # upper square first (top first) or the lower (bottom first)
        sense = -1 if mods.first == "bottom" else 1
        corners = [Q] * 4 + [-Q] * 4
        waists = (4,)
    else:
        if mods.first is not None:
            raise F3AParseError(f"{name}: 'first' goes with a start in the middle")
        sense = _sense(mods)
        corners = [Q, Q, -Q, -Q, -Q, -Q, Q, Q]
        waists = (2, 6)
    rolls: dict[int, OlanRoll] = {}
    if phrase is not None:
        # from the middle there is one waist line, otherwise two passes
        if _is_plural(phrase) != (len(waists) == 2):
            raise F3AParseError(
                f"{name}: unexpected {phrase!r}, "
                f"{'rolls (plural) go on both waist lines' if len(waists) == 2 else 'one roll goes on the waist line'}"
            )
        roll = require_roll(phrase)
        rolls = {leg: roll for leg in waists}
    return _polygon(mods, sense, corners, rolls)


# 3/4pt roll and pads are 170 m at the default parameters, line_length is 130 m
UNEQUAL_LINES = "(1.5*line_length)"

_NEGATIVE = " centre half-loop is always flown negative (inverted)"
_UPDOWN_RE = re.compile(r"^(?P<roll>.+? rolls) (?P<dir>up|down)$")


def _m_rolls(name: str, phrases: list[str]) -> tuple[OlanRoll, OlanRoll]:
    """The rolls on the up lines and on the down lines."""
    phrases = [p.removesuffix(_NEGATIVE) if p.endswith(_NEGATIVE) else p for p in phrases]
    phrases = [p for p in phrases if p != _NEGATIVE.strip()]
    if len(phrases) == 1 and _is_plural(phrases[0]) and not _UPDOWN_RE.match(phrases[0]):
        roll = require_roll(phrases[0])
        return roll, roll
    found: dict[str, OlanRoll] = {}
    for phrase in phrases:
        match = _UPDOWN_RE.match(phrase)
        if not match or match.group("dir") in found:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
        found[match.group("dir")] = require_roll(match.group("roll"))
    if set(found) != {"up", "down"}:
        raise F3AParseError(f"{name}: expected rolls on the up and the down lines, got {phrases!r}")
    return found["up"], found["down"]


@family("figure m")
def figure_m(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    up, down = _m_rolls(name, phrases)
    # Different rolls on the up and the down lines need different padding, so the
    # four lines are given one length that is longer than either roll and its
    # pads, for the figure to finish at its entry height.
    length = UNEQUAL_LINES if up.rawroll != down.rawroll else None
    clauses: list[Clause] = [Entry(mods.entry), Line(UP, length=length)]
    for stroke in (1, 2):
        # each vertical's rolls are linked, the two verticals are flown either way
        group = stroke - 1
        clauses += [Roll(up, group), StallTurn(), Line(DOWN_LINE, length=length), Roll(down, group)]
        if stroke == 1:
            # the centre half loop is always pushed, towards the direction of travel
            clauses += [Loop(Fraction(1, 2), sense=1, pull=False), Line(UP, length=length)]
    clauses.append(Exit(mods.exit if mods.exit is not None else mods.entry))
    return clauses
