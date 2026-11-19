"""F3A families, group 23 (rolls on a straight line).

Conventions decided per family (checked against the USG drawings):

- the figure is one level line with its rolls centred on it (the builder pads a
  roll that is the whole figure with a line on each side, steps.create_elements).
  An inverted entry changes only the attitude (the drawings show the line dashed).
- "reversed" rolls (23.1-23.4, 23.9-23.14, 23.23, 23.24): two rolls on the line, the
  second flown the other way round to the first, as in group 11 (one roll element
  whose angles are [+a, -a]; the builder's reversible rolls give both ways round
  for the pair). "two rolls reversed" and "two 2/4 pt. rolls reversed" are two of
  the named roll, "1 1/2 rolls reversed" is a 1 1/2 roll and its reverse (the
  drawing shows a roll and a half roll each way). The figure keeps its attitude.
- four and eight point rolls (23.5-23.8): one point roll, centred.
- slow roll (23.15, 23.16): one full roll, centred (decided 2026-11-19: flown as a
  plain roll; the rulebook gives no rate and the drawing is a plain roll symbol).
- one horizontal snap roll (23.21, 23.22): one snap roll, centred. The drawings show
  the snap symbol with the other direction in brackets: the direction is the
  pilot's choice.
- "<roll>, <snap> opposite" (23.25-23.28): the roll and then the snap flown the
  other way round, one roll element with the two parts.
- knife-edge flight (23.17, 23.18): a quarter roll, a level line flown in knife-edge,
  and a quarter roll back to the entry attitude (the drawings put the quarter rolls
  at the two ends of the line, the second the other way round to the first). The
  quarter rolls are elements of their own (Roll.alone) with the knife-edge line
  between them, the knife-edge side is a mirror option (roll_option).
- reverse knife-edge flight (23.19, 23.20): the same, with a roll reversing the
  knife-edge side in the middle of the line. The drawings put a third roll symbol
  without a label, drawn the other way round to the quarter rolls, at the centre
  of the line, on the line. This is read as a half roll (a plain symbol would be a full roll,
  which would leave the figure inverted, against the stated attitudes). The
  direction of the half roll is the pilot's choice (the template flies it as drawn).
"""

from __future__ import annotations

import re
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import AMOUNT, parse_amount, parse_roll, require_roll, signed
from .steps import Clause, Entry, Exit, Line, Roll

from .families import Modifiers, family  # isort: skip

_REVERSED_RE = re.compile(rf"^(?P<count>{AMOUNT}) (?P<roll>.+?) reversed$")
_OPPOSITE_RE = re.compile(r"^(?P<roll>.+?) opposite$")
_POINT_WORDS = {"four": 4, "eight": 8}
_HORIZONTAL_RE = re.compile(r"^(?P<amount>.*?)\s*horizontal (?P<snap>snap(?: roll)?)$")


def _roll_on_line(name: str, mods: Modifiers, rolls: list[OlanRoll]) -> list[Clause]:
    """Entry, the rolls on one centred level line, exit in the entry attitude."""
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    return [
        Entry(mods.entry),
        *[Roll(roll) for roll in rolls],
        Exit(mods.exit if mods.exit is not None else mods.entry),
    ]


def _no_phrases(name: str, phrases: list[str]) -> None:
    if phrases:
        raise F3AParseError(f"{name}: unexpected {phrases[0]!r}")


def _reversed_pair(name: str) -> list[OlanRoll]:
    """The rolls of a name such as "two 2/4-point rolls reversed" or "1 1/2 rolls reversed"."""
    match = _REVERSED_RE.match(name)
    if match and parse_amount(match.group("count")) == 2:
        roll = require_roll(match.group("roll"))
    elif match := re.match(r"^(?P<roll>.+ rolls?) reversed$", name):
        roll = require_roll(match.group("roll"))
    else:
        raise F3AParseError(f"not a pair of reversed rolls: {name!r}")
    return [roll, signed(roll, -1)]


@family(
    "1 1/2 rolls reversed",
    "two rolls reversed",
    "two 3/4-point rolls reversed",
    "two 2/2-point rolls reversed",
    "two 2/4-point rolls reversed",
    "two snap rolls reversed",
)
def rolls_reversed(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    _no_phrases(name, phrases)
    return _roll_on_line(name, mods, _reversed_pair(name))


@family("four point roll", "eight point roll")
def point_roll(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    _no_phrases(name, phrases)
    points = _POINT_WORDS[name.split()[0]]
    return _roll_on_line(name, mods, [require_roll(f"{points}-point roll")])


@family("slow roll")
def slow_roll(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    _no_phrases(name, phrases)
    return _roll_on_line(name, mods, [require_roll("roll")])


@family("one horizontal snap roll")
def horizontal_snap(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    _no_phrases(name, phrases)
    return _roll_on_line(name, mods, [require_roll("snap roll")])


@family("2/2-point roll", "2/4-point roll")
def roll_and_opposite_snap(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if len(phrases) != 1 or not (match := _OPPOSITE_RE.match(phrases[0])):
        raise F3AParseError(f"{name}: expected '<snap> opposite', got {phrases!r}")
    snap = require_roll(match.group("roll"))
    if not all(r.kind == "snap" for r in snap.roll_arr):
        raise F3AParseError(f"{name}: expected a snap roll opposite, got {phrases[0]!r}")
    return _roll_on_line(name, mods, [require_roll(f"{name}"), signed(snap, -1)])


_QUARTER = OlanRoll("1/4 roll", require_roll("1/4 roll").roll_arr)
# drawn the other way round to the quarter rolls (the template shows the reverse)
_HALF = signed(require_roll("half roll"), -1)


def _knife_edge_flight(
    name: str, mods: Modifiers, phrases: list[str], middle: OlanRoll | None
) -> list[Clause]:
    _no_phrases(name, phrases)
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    clauses: list[Clause] = [Entry(mods.entry), Roll(_QUARTER, alone=True), Line(knife_edge=True)]
    if middle is not None:
        clauses.append(Roll(middle))
    clauses += [
        Roll(_QUARTER, alone=True),
        Exit(mods.exit if mods.exit is not None else mods.entry),
    ]
    return clauses


@family("knife-edge flight")
def knife_edge_flight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _knife_edge_flight(name, mods, phrases, None)


@family("reverse knife-edge flight")
def reverse_knife_edge_flight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _knife_edge_flight(name, mods, phrases, _HALF)
