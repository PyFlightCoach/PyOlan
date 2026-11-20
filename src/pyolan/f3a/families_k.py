"""F3A families, group K (45 degree lines with a half loop and rolls on both lines).

Conventions decided per family (checked against the USG drawings):

- turnarounds: a 1/8 loop onto a 45 degree line up, a half loop that turns the
  flight round onto a 45 degree line down (heading back), and a 1/8 loop to
  level.
- closure (decided 2026-11-20, A4 review: "close at the same height; the line lengths
  need not match"): the figure finishes at its entry height. The half loop shifts the
  down line by 2 radii perpendicular to the lines, which is 1.41 radii of height, so
  with the up line as ``line_length`` the down line is ``line_length + 2*loop_radius``
  after a pulled half loop (up) and ``line_length - 2*loop_radius`` after a pushed one
  (down); each Option figure has its own (the loop's sense is the same for a plane and
  a knife-edge loop: it only turns the path through 180 degrees one way or the other).
  The expression is the padded roll's ``line_length``. A padded roll is never shorter
  than its roll plus two pads of at least 20 m, so the shorter down line cannot go
  negative; when the roll sets the length the figure no longer closes, and the layout
  has to raise ``line_length`` (or lower the radius). Before this decision both lines
  shared ``line_length`` and the exit was 1.41 radii off the entry, so BB never closed.
- the half loop's direction is the pilot's choice ("inside or outside", "up or
  down"): an Option with one figure per direction, as for any loop whose sense
  the words leave open. The first is the one the drawing shows: K.1-K.8 "down"
  (the outside loop of an upright pilot, exit below the entry), K.9-K.32 "up".
- K.1-K.8: ``<roll>, half loop (inside or outside), <roll> down`` with a roll
  centred on each 45 degree line. Rolls that are not quarters are left to the
  builder's reversible rolls.
- K.9-K.32: ``45 degree upline from upright|inverted, <roll>, knife-edge half
  loop (up or down), <roll> down, exit ...``, one of the two rolls being a
  single 1/4 roll (a 1/4 roll, or three consecutive ones, or a 3/4 snap). The
  rolls leave the wings vertical for the knife-edge loop and level again for the
  exit; the exit attitude decides their relative direction, so the two rolls and
  the loop's side are one mirror option (as for the knife-edge Immelmann turn).
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll

from .families import Modifiers, family  # isort: skip
from .families_a_c_d import _ATTITUDE, _exit_attitude  # isort: skip

_UP = frozenset({Fraction(1, 8)})
_DOWN = frozenset({Fraction(5, 8)})
_PLAIN_LOOP_RE = re.compile(r"^half loop \(inside or outside\)$")
_KE_LOOP_RE = re.compile(r"^knife-edge half loop \(up or down\)$")
_DOWN_RE = re.compile(r"^(?P<roll>.+?) down$")


def _check(name: str, mods: Modifiers) -> None:
    if mods.start is not None or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: no start height expected")


def _down_roll(name: str, phrase: str) -> OlanRoll:
    if not (match := _DOWN_RE.match(phrase)):
        raise F3AParseError(f"{name}: expected '<roll> down', got {phrase!r}")
    return require_roll(match.group("roll"))


# the down line's length by the sense of the half loop before it (+1: the path turns
# up and over, a pulled loop of an upright pilot; -1 the other way) and the same in the
# line units steps.py uses for heights (a loop radius is 0.5; the up line is two units,
# so the shorter down line stays positive)
CLOSING_LENGTH = {1: "(line_length+(2*loop_radius))", -1: "(line_length-(2*loop_radius))"}
UP_UNITS = 2.0
CLOSING_UNITS = {1: UP_UNITS + 1.0, -1: UP_UNITS - 1.0}


def _turnaround(
    entry, roll_up: OlanRoll, ke: bool, roll_down: OlanRoll, exit_attitude, first: int
) -> list[Clause]:
    """Both lines carry a roll; the half loop's sense is left open."""
    return [
        Entry(entry),
        Line(_UP, label="line up", units=UP_UNITS),
        Roll(roll_up),
        Loop(Fraction(1, 2), knife_edge=True if ke else None, first=first),
        Line(_DOWN, label="line down", length=CLOSING_LENGTH, units=CLOSING_UNITS),
        Roll(roll_down),
        Exit(exit_attitude),
    ]


# registered with the comma: "45 degree up" alone is the group 11 family, and the
# longest name wins (find_family)
@family("45 degree up,")
def forty_five_half_loop(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    _check(name, mods)
    if len(phrases) != 3 or not _PLAIN_LOOP_RE.match(phrases[1]):
        raise F3AParseError(f"{name}: expected a roll, 'half loop (inside or outside)' and a roll, got {phrases!r}")
    return _turnaround(
        mods.entry, require_roll(phrases[0]), False, _down_roll(name, phrases[2]), mods.exit, -1
    )


@family("45 degree upline from upright", "45 degree upline from inverted")
def forty_five_upline_knife_edge(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    _check(name, mods)
    if mods.entry != _ATTITUDE["upright"]:
        raise F3AParseError(f"{name}: the entry attitude is given twice")
    entry = _ATTITUDE[name.rsplit(" ", 1)[1]]
    if len(phrases) not in (3, 4) or not _KE_LOOP_RE.match(phrases[1]):
        raise F3AParseError(f"{name}: expected a roll, 'knife-edge half loop (up or down)' and a roll down, got {phrases!r}")
    roll_up, _, last, *rest = phrases
    exit_attitude = _exit_attitude(name, mods, rest)
    return _turnaround(entry, require_roll(roll_up), True, _down_roll(name, last), exit_attitude, 1)
