"""F3A families, lettered groups A (half square loop), C (split S) and D (Immelmann turn).

Conventions decided per family (checked against the USG drawings):

- half square loop (A): entry, a 1/4 loop up, a vertical upline, a 1/4 loop out
  and the exit line, flying back the way it came (a turnaround). The drawings
  put the entry and the exit on the same side, one box apart, so the figure
  starts low and finishes high (``from top``: the mirror image, high to low,
  down and back). That height difference is the figure's definition.
  - ``<roll> up`` / ``<roll> down`` (A.5-A.22): the roll is centred on the vertical
    line, "up" for a figure from the bottom, "down" from the top (checked). Whether
    each corner is pulled or pushed follows from the roll (a half roll makes the
    second corner a push), and so does the exit attitude.
  - ``from <attitude>, 1/4 roll integrated, snap-roll, 1/4 roll integrated, exit
    <attitude>`` (A.23-A.30): the first quarter roll is integrated in the first 1/4
    loop, the snap is centred on the vertical line, and the second quarter roll is
    integrated in the second 1/4 loop (which is a knife-edge loop, the wings being
    vertical at the end of the first). The two quarter rolls are one mirror option:
    the exit attitude decides their relative direction, so only both together can
    be mirrored (as in the stall turn). The snap's direction is the pilot's choice.
    ``from top upright|inverted`` gives the attitude after "from top".
- Immelmann turn (D): entry, a half loop up (its attitude follows from the roll
  after it), then the roll that ends the figure, on a line after the loop (the
  usual rule for a roll that ends a figure). A plain Immelmann has a half roll; a
  ``full roll`` replaces it. The roll direction is the pilot's choice.
  ``from upright|inverted with 1/4 roll, knife-edge half loop up|down, 3/4 roll,
  exit ...``: a 1/4 roll that starts the figure (so, as for every roll that starts
  a figure, a line follows it), a half loop in knife-edge flight and a 3/4 roll
  that ends it. The two rolls and the loop are one mirror option, the exit
  attitude deciding the relative direction of the rolls. "up" starts at the
  bottom, "down" at the top. The drawings put the rolls next to the loop; ours
  follow the shared rule for a roll at the start or end of a figure.
- split S (C): a full roll that starts the figure, and then a half loop down from
  the top. The drawings put the arrow at the end of the entry line, next to the
  loop (as for the double Immelmann, the shared rule puts the line after the roll).
"""

from __future__ import annotations

import re
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import is_quarter, require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll

from .families import Modifiers, _polygon, _sense, family  # isort: skip

_ATTITUDE = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}
_UPDOWN_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")
_FROM_RE = re.compile(r"^(?:from )?(?P<att>upright|inverted)$")
_EXIT_RE = re.compile(r"^exit (?P<att>upright|inverted)$")
_INTEGRATED_RE = re.compile(r"^(?P<roll>.+?) integrated$")
_KE_HALF_RE = re.compile(r"^knife-edge half loop (?P<dir>up|down)$")


def _check_direction(name: str, mods: Modifiers, direction: str) -> None:
    expected = "down" if mods.start == "top" else "up"
    if direction != expected:
        raise F3AParseError(
            f"{name}: {direction!r} for a figure from {mods.start or 'bottom'}, expected {expected!r}"
        )


def _check_start(name: str, mods: Modifiers) -> None:
    if mods.start not in (None, "top") or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: a start at {mods.start!r} is not supported")


def _attitude_after(name: str, mods: Modifiers, phrase: str) -> p.Orientation:
    """The entry attitude of 'from upright' (or 'upright' after 'from top')."""
    if not (match := _FROM_RE.match(phrase)):
        raise F3AParseError(f"{name}: expected 'from <attitude>', got {phrase!r}")
    if mods.entry != p.Orientation.UPRIGHT:
        raise F3AParseError(f"{name}: the entry attitude is given twice")
    return _ATTITUDE[match.group("att")]


def _exit_attitude(name: str, mods: Modifiers, rest: list[str]) -> p.Orientation:
    """The exit attitude: 'exit inverted' is a shared modifier, 'exit upright' is not."""
    exit_attitude = mods.exit
    if rest:
        if exit_attitude is not None or len(rest) > 1 or not (match := _EXIT_RE.match(rest[0])):
            raise F3AParseError(f"{name}: unexpected {rest[0]!r}")
        exit_attitude = _ATTITUDE[match.group("att")]
    if exit_attitude is None:
        raise F3AParseError(f"{name}: the exit attitude is missing")
    return exit_attitude


def _check_total(name: str, roll: OlanRoll, turns: float, phrase: str) -> None:
    if abs(abs(roll.total()) - turns) > 1e-9:
        raise F3AParseError(f"{name}: expected a {turns} roll, got {phrase!r}")


@family("half square loop")
def half_square_loop(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    _check_start(name, mods)
    sense = _sense(mods)
    quarter = Fraction(1, 4)
    theta = (quarter * sense) % 1
    if len(phrases) == 1:
        # A.5-A.22: one roll on the vertical line
        match = _UPDOWN_RE.match(phrases[0])
        if not match:
            raise F3AParseError(f"{name}: unexpected {phrases[0]!r}")
        _check_direction(name, mods, match.group("dir"))
        return _polygon(mods, sense, [quarter, quarter], {1: require_roll(match.group("roll"))})
    # A.23-A.30: quarter rolls integrated in both corners, a snap on the vertical.
    # "exit inverted" is a shared modifier, so only "exit upright" is left in phrases
    if len(phrases) not in (4, 5):
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    start, first, snap, second, *rest = phrases
    att = _attitude_after(name, mods, start)
    exit_attitude = _exit_attitude(name, mods, rest)
    rolls: list[OlanRoll] = []
    for phrase in (first, second):
        if not (match := _INTEGRATED_RE.match(phrase)):
            raise F3AParseError(f"{name}: expected a roll 'integrated', got {phrase!r}")
        roll = require_roll(match.group("roll"))
        _check_total(name, roll, 0.25, phrase)
        rolls.append(roll)
    snap_roll = require_roll(snap)
    if not all(r.kind == "snap" for r in snap_roll.roll_arr):
        raise F3AParseError(f"{name}: expected a snap, got {snap!r}")
    return [
        Entry(att),
        Loop(quarter, sense=sense, roll=rolls[0], integrated=True),
        Line(frozenset({theta}), label="vertical line"),
        Roll(snap_roll),
        Loop(quarter, sense=sense, roll=rolls[1], integrated=True),
        Exit(exit_attitude),
    ]


@family("immelmann turn")
def immelmann_turn(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: no start height expected")
    if len(phrases) <= 1:
        # the half loop and the roll that ends the figure (a half roll unless stated)
        roll = require_roll(phrases[0] if phrases else "half roll")
        return [Entry(mods.entry), Loop(Fraction(1, 2), sense=1), Roll(roll), Exit(mods.exit)]
    if len(phrases) not in (4, 5):
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    start, first, loop, last, *rest = phrases
    att = _attitude_after(name, mods, start)
    if not (ke := _KE_HALF_RE.match(loop)):
        raise F3AParseError(f"{name}: expected 'knife-edge half loop up|down', got {loop!r}")
    exit_attitude = _exit_attitude(name, mods, rest)
    rolls = []
    for phrase, turns in ((first, 0.25), (last, 0.75)):
        roll = require_roll(phrase)
        _check_total(name, roll, turns, phrase)
        rolls.append(roll)
    sense = 1 if ke.group("dir") == "up" else -1
    return [
        Entry(att),
        Roll(rolls[0]),
        Loop(Fraction(1, 2), sense=sense, knife_edge=True),
        Roll(rolls[1]),
        Exit(exit_attitude),
    ]


@family("split s")
def split_s(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start != "top" or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: expected 'from top'")
    if len(phrases) != 1:
        raise F3AParseError(f"{name}: expected one roll, got {phrases!r}")
    return [
        Entry(mods.entry),
        Roll(require_roll(phrases[0])),
        Loop(Fraction(1, 2), sense=-1),
        Exit(mods.exit),
    ]
