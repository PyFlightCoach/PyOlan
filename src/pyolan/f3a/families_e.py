"""F3A families, group E (Figure 9 and Figure 6).

Conventions decided per family (checked against the USG drawings):

- Figure 9 and Figure 6 are a 1/4 loop and a 3/4 loop in opposite senses, joined by a
  vertical line, flown as the drawings show them (turnarounds, the exit heads back
  the way the entry came). The digit is the loop: the 9 has its 3/4 loop at the top
  and the 6 at the bottom.

    9 from bottom:         1/4 loop up (pulled), line up, 3/4 loop over the top
    9 from middle (top first):  3/4 loop up and over, line down, 1/4 loop out
    6 from top:            1/4 loop down, line down, 3/4 loop under the bottom
    6 from middle (bottom first): 3/4 loop down and under, line up, 1/4 loop out

  The heights follow from the loops and the one vertical line (the middle starts
  have the 3/4 loop first; "top first" and "bottom first" are checked against the
  digit when given). The vertical line crosses the line of the 3/4 loop's far side.
- "<roll> up" or "<roll> down" is the roll on the vertical line (up for 9 from bottom
  and 6 from middle, down for the other two), centred on the line. The direction of
  the rolls is the pilot's choice, so is the entry (a stated "upright" or "inverted"
  or "inverted entry"); the exit attitude is what the rolls and loops give, and a
  stated "exit upright" / "exit inverted" is checked against it.
- "with integrated roll in top 180 degree of loop" (9 from bottom) and "integrated 1/2
  roll on bottom 180 degree of loop" (6 from top): the roll is spread over the first
  half of the 3/4 loop, so the loop is built as a 1/2 loop carrying the roll and a
  1/4 loop (as the vertical eight's waist rolls). Without an amount the roll is one
  roll (E.49/E.50: the stated exit attitude is only possible with a whole roll).
- the knife-edge versions: a 1/4 roll (or "3 consecutive 1/4 rolls", or a 3/4 snap
  roll) on the vertical line (9 from bottom, 6 from top; the snap goes with the
  6 from top) or on the entry line (the middle starts), the 3/4 loop in knife-edge,
  and the second 1/4 roll (or three) on the exit line (9 from bottom, 6 from top) or
  on the vertical line (the middle starts). The roll directions, the loop yaw and the
  final rolls follow from the stated exit attitude and are one mirror option.
"""

from __future__ import annotations

import re
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import is_quarter, require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll

from .families import Modifiers, family  # isort: skip

_UP_DOWN_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")
_INTEGRATED_RE = re.compile(
    r"^integrated (?:(?P<roll>.*?roll) )?(?:in|on) (?P<where>top|bottom) 180 degree of loop$"
)
_KE_LOOP = "3/4 knife-edge loop"
_ATTITUDES = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}
_THREE_QUARTER = Fraction(3, 4)
_QUARTER = Fraction(1, 4)
_HALF = Fraction(1, 2)

# (digit, start) -> (signed 3/4 loop and 1/4 loop in flight order, direction of the line)
# the senses are the figure plane's: + is towards +Z when travelling +X
_SHAPES: dict[tuple[str, str], tuple[list[Fraction], str]] = {
    ("9", "bottom"): ([_QUARTER, -_THREE_QUARTER], "up"),
    ("9", "middle"): ([_THREE_QUARTER, -_QUARTER], "down"),
    ("6", "top"): ([-_QUARTER, _THREE_QUARTER], "down"),
    ("6", "middle"): ([-_THREE_QUARTER, _QUARTER], "up"),
}
_FIRST_HALF = {("9", "middle"): "top", ("6", "middle"): "bottom"}


def _shape(name: str, mods: Modifiers) -> tuple[list[Fraction], str, bool]:
    """The signed loops, the direction of the vertical line and whether the loop
    with the 3/4 comes first (the middle starts)."""
    digit = name.split()[-1]
    start = mods.start
    if start is None or mods.entry_form or (digit, start) not in _SHAPES:
        raise F3AParseError(
            f"{name}: only {', '.join(f'from {s}' for d, s in _SHAPES if d == digit)} is described, "
            f"got {start!r}"
        )
    if mods.first is not None and mods.first != _FIRST_HALF.get((digit, start)):
        raise F3AParseError(f"{name}: from {start} {mods.first} first is not this figure")
    corners, direction = _SHAPES[(digit, start)]
    return corners, direction, abs(corners[0]) == _THREE_QUARTER


def _attitudes(name: str, mods: Modifiers, phrases: list[str]) -> tuple[p.Orientation, p.Orientation | None, list[str]]:
    """The entry attitude (the shared modifier, or a stated one) and the exit, and the
    phrases that are neither."""
    entry = mods.entry
    exit_attitude = mods.exit
    stated_entry = mods.entry == p.Orientation.INVERTED
    rest: list[str] = []
    for phrase in phrases:
        if phrase in _ATTITUDES:
            if stated_entry:
                raise F3AParseError(f"{name}: the entry attitude is given twice")
            stated_entry, entry = True, _ATTITUDES[phrase]
        elif phrase.startswith("exit ") and phrase[5:] in _ATTITUDES:
            if exit_attitude is not None:
                raise F3AParseError(f"{name}: the exit attitude is given twice")
            exit_attitude = _ATTITUDES[phrase[5:]]
        else:
            rest.append(phrase)
    return entry, exit_attitude, rest


def _vertical_roll(name: str, phrase: str, direction: str) -> OlanRoll:
    match = _UP_DOWN_RE.match(phrase)
    if not match:
        raise F3AParseError(f"{name}: unexpected {phrase!r}")
    if match.group("dir") != direction:
        raise F3AParseError(
            f"{name}: a roll {match.group('dir')} but the vertical line goes {direction}"
        )
    return require_roll(match.group("roll"))


def _plain(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    corners, direction, _ = _shape(name, mods)
    entry, exit_attitude, rest = _attitudes(name, mods, phrases)
    if len(rest) != 1:
        raise F3AParseError(f"{name}: expected one roll on the vertical line, got {phrases!r}")
    roll = _vertical_roll(name, rest[0], direction)
    theta = corners[0]
    return [
        Entry(entry),
        Loop(corners[0], sense=1),
        Line(frozenset({theta % 1}), label="vertical"),
        Roll(roll),
        Loop(corners[1], sense=1),
        Exit(exit_attitude),
    ]


def _integrated(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    corners, _, three_quarter_first = _shape(name, mods)
    if three_quarter_first:
        raise F3AParseError(f"{name}: an integrated roll is only described from bottom or top")
    entry, exit_attitude, rest = _attitudes(name, mods, phrases)
    if len(rest) != 1 or not (match := _INTEGRATED_RE.match(rest[0])):
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    far = "top" if mods.start == "bottom" else "bottom"
    if match.group("where") != far:
        raise F3AParseError(
            f"{name}: the loop's {match.group('where')} 180 degrees, not its {far}, from {mods.start}"
        )
    roll = require_roll(match.group("roll") or "roll")
    big = corners[1]
    sign = 1 if big > 0 else -1
    return [
        Entry(entry),
        Loop(corners[0], sense=1),
        Line(frozenset({corners[0] % 1}), label="vertical"),
        Loop(sign * _HALF, sense=1, roll=roll, integrated=True),
        Loop(sign * _QUARTER, sense=1),
        Exit(exit_attitude),
    ]


def _knife_edge(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    corners, direction, three_quarter_first = _shape(name, mods)
    entry, exit_attitude, rest = _attitudes(name, mods, phrases)
    if len(rest) != 3 or rest[1] != _KE_LOOP:
        raise F3AParseError(
            f"{name}: expected a roll, the {_KE_LOOP} and a roll, got {phrases!r}"
        )
    if three_quarter_first:
        # the rolls are not on the vertical line: before the loop (on the entry line)
        # and on the vertical line after it
        if _UP_DOWN_RE.match(rest[0]) or _UP_DOWN_RE.match(rest[2]):
            raise F3AParseError(f"{name}: no up or down expected with the rolls")
        first, second = require_roll(rest[0]), require_roll(rest[2])
    else:
        first = _vertical_roll(name, rest[0], direction)
        if _UP_DOWN_RE.match(rest[2]):
            raise F3AParseError(f"{name}: unexpected {rest[2]!r}")
        second = require_roll(rest[2])
    for roll in (first, second):
        if not is_quarter(roll):
            raise F3AParseError(f"{name}: {roll.rawroll!r} does not leave the wings vertical")
    vertical = Line(frozenset({corners[0] % 1}), label="vertical")
    if three_quarter_first:
        return [
            Entry(entry),
            Roll(first),
            Loop(corners[0], sense=1, knife_edge=True),
            vertical,
            Roll(second),
            Loop(corners[1], sense=1, knife_edge=False),
            Exit(exit_attitude),
        ]
    return [
        Entry(entry),
        Loop(corners[0], sense=1, knife_edge=False),
        vertical,
        Roll(first),
        Loop(corners[1], sense=1, knife_edge=True),
        Roll(second),
        Exit(exit_attitude),
    ]


@family("figure 9", "figure 6", entry_heights=True)
def figure_9_and_6(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if any(_INTEGRATED_RE.match(phrase) for phrase in phrases):
        return _integrated(name, mods, phrases)
    if _KE_LOOP in phrases:
        return _knife_edge(name, mods, phrases)
    return _plain(name, mods, phrases)
