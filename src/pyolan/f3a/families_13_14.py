"""F3A families, groups 13 (hourglass) and 14 (vertical eight).

Conventions decided per family (checked against the USG drawings):

- hourglass (13): two triangles meeting at their apex, in the vertical plane.
  From the bottom (the default; ``(top entry)`` is the mirror image about the
  entry height): the entry line is the base of the lower triangle, then a 3/8
  loop, a 45 degree upline going back, a 3/8 loop the other way, the top line,
  a 3/8 loop, a 45 degree downline crossing the upline, a 3/8 loop back to the
  base and the exit line. Corners are 3/8, 3/8, 3/8, 3/8 and the two 45 degree
  lines are the same length (one shared ``line_length``), so the figure
  finishes at its entry height. Plural rolls ("half rolls up and down", "down
  and up" from the top) put the same roll on both 45 degree lines, centred on
  the line, where the lines cross as the drawings show.
- hourglass from the middle (``(middle entry, top first)`` or ``bottom
  first``): the same hourglass entered at the crossing of its diagonals. Top
  first: 1/8 loop onto a 45 degree line up to the top right, 3/8 loop, the top
  line flown back, 3/8 loop, the long 45 degree downline through the entry
  height to the bottom right, 3/8 loop, the base flown back, 3/8 loop, a 45
  degree line up to the entry height and a 1/8 loop to the exit line. Bottom
  first is the mirror image. The long diagonal is one ``line_length`` (as in
  the other hourglass); the two half diagonals are the same length,
  ``(line_length - 2*(sqrt(2)-1)*loop_radius)/2`` (a builder expression), which puts the crossing at the
  entry height, so the figure finishes at its entry height too. A single roll
  ("half roll down" top first, "up" bottom first) goes on the long diagonal,
  centred at the crossing, as the drawings show; the half diagonals have none.
  A roll and its pads longer than ``line_length`` would lengthen the diagonal.
- vertical eight (14): loops of one radius in the vertical plane, one above the
  other and tangent at the waist, where the path is level and flown the same
  direction in both. From the bottom: 1/2 pulled loop up to the waist, a full
  push loop (the upper circle), a 1/2 pull loop down (the other half of the
  lower circle). From the top it is the mirror image. From the middle (the
  waist, entry and exit on its level): a full pulled loop up (the upper circle),
  then a full pushed loop down. "top first" and no word are the same; "bottom
  first" swaps them.
- vertical eight rolls: at the waist, where the loops join, and they are rolls
  on a short line there (the roll and its pads, no longer than they need,
  ``loop_radius`` is the line length given to the builder). Plural rolls ("half
  rolls", "two half roll") are at both waist crossings (after the first half loop
  and after the full loop); "half roll after first half loop" is the first only;
  a single "half roll" from the middle is at the one waist crossing. The
  geometric path does not change with a roll: only pull and push do.
- knife-edge vertical eight: the same shape, flown in knife-edge, with a 1/4 roll
  on the entry and exit lines (as the other knife-edge families).
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll

from .families import Modifiers, _is_plural, _polygon, _sense, family  # isort: skip

SQRT2_MINUS_1 = 0.41421356237309503

# the long diagonal of a middle entry hourglass is one line_length; the half
# diagonals are equal and put the crossing at the entry height
HALF_DIAGONAL = f"((line_length-({2 * SQRT2_MINUS_1}*loop_radius))/2)"

# the line at the waist of a vertical eight that holds a roll: as short as the
# roll and its pads allow
WAIST_LINE = "loop_radius"

_BOTH_RE = re.compile(r"^(?P<roll>.+? rolls) (?P<dirs>up and down|down and up)$")
_ONE_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")


def _hourglass_roll(name: str, phrases: list[str], first: str | None) -> tuple[OlanRoll | None, bool]:
    """The roll phrase and whether it is on both 45 degree lines (or just the long one)."""
    if not phrases:
        return None, False
    if len(phrases) != 1:
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    phrase = phrases[0]
    if match := _BOTH_RE.match(phrase):
        if first is not None:
            raise F3AParseError(f"{name}: {phrase!r}: from the middle only one line is rolled")
        return require_roll(match.group("roll")), True
    if (match := _ONE_RE.match(phrase)) and not _is_plural(match.group("roll")):
        if first is None:
            raise F3AParseError(f"{name}: unexpected {phrase!r}, expected rolls up and down")
        # the long diagonal is the down line when the top goes first, the up line otherwise
        if match.group("dir") != ("down" if first == "top" else "up"):
            raise F3AParseError(
                f"{name}: with the {first} first the long line is the "
                f"{'down' if first == 'top' else 'up'} line, not {phrase!r}"
            )
        return require_roll(match.group("roll")), False
    raise F3AParseError(f"{name}: unexpected {phrase!r}")


@family("hourglass", entry_heights=True)
def hourglass(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    roll, both = _hourglass_roll(name, phrases, mods.first)
    if mods.start == "middle":
        if mods.first is None:
            raise F3AParseError(f"{name}: from the middle, say whether the top or bottom goes first")
        sense = 1 if mods.first == "top" else -1
        corners = [Fraction(1, 8), Fraction(3, 8), Fraction(3, 8), Fraction(-3, 8), Fraction(-3, 8), Fraction(-1, 8)]
        lengths = {1: HALF_DIAGONAL, 5: HALF_DIAGONAL}
        return _polygon(mods, sense, corners, {3: roll} if roll else {}, lengths=lengths)
    if mods.first is not None:
        raise F3AParseError(f"{name}: 'first' goes with a start in the middle")
    corners = [Fraction(3, 8), Fraction(-3, 8), Fraction(-3, 8), Fraction(3, 8)]
    return _polygon(mods, _sense(mods), corners, {1: roll, 3: roll} if roll else {})


# ---------------------------------------------------------------- vertical eight


def _eight_rolls(
    name: str, phrases: list[str], middle: bool
) -> dict[int, OlanRoll]:
    """Rolls by waist crossing (1 after the first loop, 2 after the second)."""
    if not phrases:
        return {}
    if len(phrases) != 1:
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    phrase = phrases[0]
    two = re.match(r"^two (?P<roll>.+?)s?$", phrase)
    after_first = re.match(r"^(?P<roll>.+?) after first half loop$", phrase)
    if middle:
        # one waist crossing between the two circles
        if two or after_first or _is_plural(phrase):
            raise F3AParseError(f"{name}: from the middle there is one crossing, got {phrase!r}")
        return {1: require_roll(phrase)}
    if after_first:
        return {1: require_roll(after_first.group("roll"))}
    if two:
        roll = require_roll(two.group("roll"))
        return {1: roll, 2: roll}
    if _is_plural(phrase):
        roll = require_roll(phrase)
        return {1: roll, 2: roll}
    raise F3AParseError(f"{name}: unexpected {phrase!r}")


def _vertical_eight(
    name: str, mods: Modifiers, phrases: list[str], knife_edge: bool
) -> list[Clause]:
    middle = mods.start == "middle"
    if mods.entry_form and not middle:
        raise F3AParseError(f"{name}: unexpected the {mods.start} entry")
    if middle:
        sense = -1 if mods.first == "bottom" else 1
        loops = [Fraction(1), Fraction(-1)]
    else:
        if mods.first is not None:
            raise F3AParseError(f"{name}: 'first' goes with a start in the middle")
        sense = _sense(mods)
        loops = [Fraction(1, 2), Fraction(-1), Fraction(1, 2)]
    rolls = _eight_rolls(name, phrases, middle)
    ke = True if knife_edge else None
    quarter = require_roll("1/4 roll")
    clauses: list[Clause] = [Entry(mods.entry)]
    if knife_edge:
        clauses.append(Roll(quarter))
    for i, amount in enumerate(loops, start=1):
        clauses.append(Loop(amount, sense=sense, knife_edge=ke))
        if i in rolls:
            clauses.append(Line(knife_edge=ke, label="waist", length=WAIST_LINE))
            clauses.append(Roll(rolls[i]))
    if knife_edge:
        clauses.append(Roll(quarter))
    clauses.append(Exit(mods.exit if mods.exit is not None else mods.entry if knife_edge else None))
    return clauses


@family("vertical eight", entry_heights=True)
def vertical_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _vertical_eight(name, mods, phrases, knife_edge=False)


@family("vertical knife-edge eight", entry_heights=True)
def vertical_knife_edge_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _vertical_eight(name, mods, phrases, knife_edge=True)
