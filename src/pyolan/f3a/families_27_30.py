"""F3A groups 27 (infinite loop), 28 (Figure H), 29 (half clover leaf) and 30 (diamond in a loop).

These descriptions are written step by step but start with the figure's name and a full
stop (``Infinite loop. From upright, past centre, ...``), so they are read here by
``named_step_clauses`` (called from parser.description_clauses) rather than as a
family plus modifiers. Each figure expects its steps in order and says which one is
unexpected.

Conventions decided per figure (checked against the USG drawings):

- infinite loop (27): a figure eight lying on its side with a 45 degree diagonal. The
  entry line (flown "past centre", which has no length of its own) is followed by a
  1/2 loop up with its half roll spread over it, a 1/8 loop onto the downward diagonal,
  the diagonal with its two snaps, a 1/8 loop back to level (the other way round) and a
  1/2 loop, again up, with a half roll spread over it, so the figure leaves the way it
  came in, at the entry height. The loops before the diagonal turn one way, those after
  the other, as drawn. The two snaps (or two 1/2 rolls on the exit line) are "opposite":
  one roll element whose second roll is the reverse of the first (the builder's
  reversible roll flips the pair). The four 1/4 rolls of 27.3/27.4 are one roll on the
  entry line. The diagonal is ``(4.8284*loop_radius)`` long, which makes the second
  half loop end at the entry height (the figure starts and ends in the middle).
- Figure H (28): 1/4 loop up, a vertical upline with its 3/4 snap, a stall turn, a short
  downline, a 1/4 knife-edge loop, the horizontal knife-edge line with its roll, a
  1/4 knife-edge loop up, a short upline, a stall turn, a downline with its 3/4 snap
  and a 1/4 loop out. The words end "3/4 snap-roll, 1/4 roll", but that 1/4 roll would leave
  the figure in knife-edge flight with no upright or inverted exit, and the drawings show a
  1/4 loop and no roll there (the first half has "1/4 loop, 3/4 snap-roll", so the figure is
  symmetrical): it is read as the 1/4 loop out (see the report on the catalogue text). The
  USG drawings label the snaps "1 1/4" for the upright entries (28.1, 28.2) and "3/4" for the
  inverted ones; the words say 3/4 in all four and are followed. The two short lines (a quarter of
  ``line_length``, as drawn) are in the drawings but not in the words; they are equal, so the
  figure ends at its entry height whatever their length. "line with roll" is read as a full roll, as a
  lone "roll" is everywhere else, and the drawing has no amount on it. The three quarter
  rolls (two snaps, the 1/4 roll) are one mirror option, since the exit attitude depends
  on their relative directions. The loops and the roll all turn the same way, as drawn.
- half clover leaf (29): 1/4 loop up (down from the top), a vertical line with its 3/4
  roll, two 3/4 knife-edge loops all turning the way the entry loop did (so the first
  one is flown back in the entry direction), joined by a horizontal line ``2*loop_radius``
  long (the loops are tangent to the vertical line then) carrying the snap-roll, and a
  vertical line with its 3/4 roll back down. The up and down verticals have the same
  length, so the figure ends at its entry height. "from top" is the mirror image.
- diamond in a loop (30): a loop with two opposite half rolls (one roll element
  [+1/2, -1/2] spread over the whole loop, so each half roll is spread over a half loop),
  then a square loop on corner (the shape of 06, corners 1/8, 1/4, 1/4, 1/4, 1/8) with a
  half roll in each leg. "Radii for loop and square loop can be different" gives the
  corners of the diamond a radius parameter of their own, ``diamond_radius``, compared
  like the loop radius. The USG text does not say whether the loop is pulled or pushed
  (the rulebook does: pulled or pushed according to the entry attitude, the loop going
  up from the bottom and down from the top).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import parse_roll, require_roll, signed
from .steps import (
    DOWN_LINE,
    LEVEL,
    UP,
    Clause,
    Entry,
    Exit,
    Line,
    Loop,
    Roll,
    StallTurn,
)

_ATTITUDE = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}
_ATT = r"(?P<att>upright|inverted)"
Q, E = Fraction(1, 4), Fraction(1, 8)

# the diagonal of the infinite loop: 2*(1+sqrt(2)) loop radii (a loop radius is 0.5 line units)
DIAGONAL_FACTOR = 2 * (1 + math.sqrt(2))
DIAGONAL = f"({DIAGONAL_FACTOR:.4f}*loop_radius)"
DIAGONAL_UNITS = DIAGONAL_FACTOR * 0.5
DIAGONAL_DOWN = frozenset({Fraction(5, 8)})

# the short lines either side of the knife-edge flight of Figure H (about a quarter of the
# verticals in the drawings)
SHORT_LINE = "(0.25*line_length)"
SHORT_UNITS = 0.25

# the line joining the two lobes of the half clover leaf: two loop radii (one line unit)
LOBE_LINE = "(2*loop_radius)"

DIAMOND_RADIUS = ("diamond_radius", 25.0)  # name, default in m


# ---------------------------------------------------------------- reading the steps


class _Steps:
    """The phrases of a description, read in order."""

    def __init__(self, name: str, phrases: list[str]):
        self.name, self.phrases, self.at = name, phrases, 0

    def peek(self) -> str | None:
        return self.phrases[self.at] if self.at < len(self.phrases) else None

    def take(self, pattern: str | re.Pattern, what: str) -> re.Match:
        """The next phrase, which must match the pattern."""
        phrase = self.peek()
        if phrase is None:
            raise F3AParseError(f"{self.name}: expected {what}, the description ends")
        if not (match := re.fullmatch(pattern, phrase)):
            raise F3AParseError(f"{self.name}: expected {what}, got {phrase!r}")
        self.at += 1
        return match

    def take_if(self, pattern: str | re.Pattern) -> re.Match | None:
        phrase = self.peek()
        if phrase is not None and (match := re.fullmatch(pattern, phrase)):
            self.at += 1
            return match
        return None

    def done(self) -> None:
        if self.at < len(self.phrases):
            raise F3AParseError(f"{self.name}: unexpected {self.phrases[self.at]!r}")


def _roll(steps: _Steps, pattern: str, what: str) -> OlanRoll:
    return require_roll(steps.take(pattern, what).group(0))


def _opposite(phrase: str) -> OlanRoll:
    """``two opposite snap rolls``: one roll element, the second reversed."""
    match = re.fullmatch(r"two opposite (?P<one>.+?)s", phrase)
    roll = parse_roll(match.group("one")) if match else None
    if roll is None:
        raise F3AParseError(f"not two opposite rolls: {phrase!r}")
    return OlanRoll(phrase, roll.roll_arr + signed(roll, -1).roll_arr)


_FROM = rf"from {_ATT}"
_EXIT = rf"exit {_ATT}"
_PULL_PUSH = {"pulled": True, "pushed": False, None: None}


def _entry(steps: _Steps) -> p.Orientation:
    return _ATTITUDE[steps.take(_FROM, "'from upright|inverted'").group("att")]


def _exit(steps: _Steps) -> Exit:
    attitude = _ATTITUDE[steps.take(_EXIT, "'exit upright|inverted'").group("att")]
    steps.done()
    return Exit(attitude)


# ---------------------------------------------------------------- 27 infinite loop

_LOOP_STEP = r"(?P<amount>\d/\d) (?:(?P<pp>pushed|pulled) )?loop(?: with integrated (?P<roll>.+))?"


def _infinite_loop_loop(steps: _Steps, amount: Fraction, sense: int) -> Loop:
    match = steps.take(_LOOP_STEP, f"a {amount} loop")
    if Fraction(match.group("amount")) != amount:
        raise F3AParseError(
            f"{steps.name}: expected a {amount} loop, got {match.group(0)!r}"
        )
    roll = require_roll(match.group("roll")) if match.group("roll") else None
    return Loop(
        amount,
        sense=sense,
        pull=_PULL_PUSH[match.group("pp")],
        roll=roll,
        integrated=roll is not None,
    )


def infinite_loop(steps: _Steps) -> list[Clause]:
    clauses: list[Clause] = [Entry(_entry(steps))]
    steps.take_if(r"past centre")
    if steps.peek() and "consecutive" in steps.peek():
        clauses.append(Roll(_roll(steps, r"four consecutive 1/4 rolls", "four consecutive 1/4 rolls")))
    half, eighth = Fraction(1, 2), Fraction(1, 8)
    clauses.append(_infinite_loop_loop(steps, half, 1))
    clauses.append(_infinite_loop_loop(steps, eighth, 1))
    clauses.append(Line(DIAGONAL_DOWN, length=DIAGONAL, units=DIAGONAL_UNITS))
    clauses.append(Roll(_opposite(steps.take(r"two opposite snap rolls", "two opposite snap-rolls").group(0))))
    clauses.append(_infinite_loop_loop(steps, eighth, -1))
    clauses.append(_infinite_loop_loop(steps, half, -1))
    if steps.peek() and steps.peek().startswith("two opposite"):
        clauses.append(Roll(_opposite(steps.take(r"two opposite 1/2 rolls", "two opposite 1/2 rolls").group(0))))
    clauses.append(_exit(steps))
    return clauses


# ---------------------------------------------------------------- 28 Figure H


def figure_h(steps: _Steps) -> list[Clause]:
    attitude = _entry(steps)
    steps.take(r"1/4 loop", "a 1/4 loop")
    snap = _roll(steps, r"3/4 snap roll", "a 3/4 snap-roll")
    steps.take(r"stall turn", "a stall turn")
    steps.take(r"1/4 knife-edge loop", "a 1/4 knife-edge loop")
    steps.take(r"line with roll", "a line with roll")
    steps.take(r"1/4 knife-edge loop", "a 1/4 knife-edge loop")
    steps.take(r"stall turn", "a stall turn")
    steps.take(r"3/4 snap roll", "a 3/4 snap-roll")
    # the catalogue ends "3/4 snap-roll, 1/4 roll", but a 1/4 roll after the last
    # snap would leave the figure in knife-edge flight, with no upright or inverted
    # exit. The drawings have a 1/4 loop out there and no roll (and the first half has
    # the matching "1/4 loop" before its snap): the word is read as the loop out.
    steps.take(r"1/4 roll", "a 1/4 roll (the 1/4 loop out)")
    full_roll = require_roll("roll")
    return [
        Entry(attitude),
        Line(UP),
        Roll(snap),
        StallTurn(),
        Line(DOWN_LINE, length=SHORT_LINE, units=SHORT_UNITS),
        Loop(Q, sense=1, knife_edge=True),
        Line(LEVEL, knife_edge=True),
        Roll(full_roll),
        Loop(Q, sense=1, knife_edge=True),
        Line(UP, length=SHORT_LINE, units=SHORT_UNITS),
        StallTurn(),
        Roll(snap),
        Loop(Q, sense=1),
        _exit(steps),
    ]


# ---------------------------------------------------------------- 29 half clover leaf


def half_clover_leaf(steps: _Steps) -> list[Clause]:
    start = steps.take(rf"from (?P<start>top|bottom) {_ATT}", "'from top|bottom upright|inverted'")
    sense = -1 if start.group("start") == "top" else 1
    roll = _roll(steps, r"3/4 roll", "a 3/4 roll")
    steps.take(r"3/4 knife-edge loop", "a 3/4 knife-edge loop")
    snap = _roll(steps, r"snap roll", "a snap-roll")
    steps.take(r"3/4 knife-edge loop", "a 3/4 knife-edge loop")
    steps.take(r"3/4 roll", "a 3/4 roll")
    three_quarter = Fraction(3, 4)
    return [
        Entry(_ATTITUDE[start.group("att")]),
        Line(DOWN_LINE if sense == -1 else UP),
        Roll(roll),
        Loop(three_quarter, sense=sense, knife_edge=True),
        Line(LEVEL, knife_edge=True, length=LOBE_LINE),
        Roll(snap),
        Loop(three_quarter, sense=sense, knife_edge=True),
        Roll(roll),
        _exit(steps),
    ]


# ---------------------------------------------------------------- 30 diamond in a loop


def diamond_in_a_loop(steps: _Steps) -> list[Clause]:
    start = steps.take(rf"from (?P<start>top|bottom) {_ATT}", "'from top|bottom upright|inverted'")
    sense = -1 if start.group("start") == "top" else 1
    loop = steps.take(
        r"(?:(?P<pp>pulled|pushed) )?loop with two opposite integrated half-rolls",
        "a loop with two opposite integrated half-rolls",
    )
    # the rulebook states the sense (the USG words do not): a loop from the bottom goes
    # up and from the top down, so it is pulled when upright from the bottom or
    # inverted from the top
    stated = _PULL_PUSH[loop.group("pp")]
    pulled = (sense == 1) == (start.group("att") == "upright")
    if stated is not None and stated != pulled:
        raise F3AParseError(
            f"diamond in a loop: {start.group(0)} gives a "
            f"{'pulled' if pulled else 'pushed'} loop, not a {loop.group('pp')} one"
        )
    steps.take(
        r"square loop on corner with half-roll in each leg",
        "a square loop on corner with half-roll in each leg",
    )
    half = require_roll("half roll")
    pair = OlanRoll("two opposite half rolls", half.roll_arr + signed(half, -1).roll_arr)
    clauses: list[Clause] = [
        Entry(_ATTITUDE[start.group("att")]),
        # one loop, with a half roll spread over each of its halves
        Loop(Fraction(1), sense=sense, roll=pair, integrated=True),
    ]
    theta = Fraction(0)
    corners = [E, Q, Q, Q, E]
    for leg, amount in enumerate(corners, start=1):
        clauses.append(Loop(amount, sense=sense, radius=DIAMOND_RADIUS))
        theta = (theta + amount * sense) % 1
        if leg < len(corners):
            clauses += [Line(frozenset({theta}), label=f"leg {leg}"), Roll(half)]
    clauses.append(_exit(steps))
    return clauses


# ---------------------------------------------------------------- entry point

_FIGURES: dict[str, Callable[[_Steps], list[Clause]]] = {
    "infinite loop": infinite_loop,
    "figure h": figure_h,
    "half clover leaf": half_clover_leaf,
    "diamond in a loop": diamond_in_a_loop,
}
_NAMED_RE = re.compile(rf"^(?P<name>{'|'.join(_FIGURES)})\.? (?P<rest>.*)$")


def named_step_clauses(text: str) -> list[Clause] | None:
    """The clauses of a ``<name>. from ...`` description of groups 27-30, or None if
    the text is not one."""
    match = _NAMED_RE.match(text)
    if not match:
        return None
    name, rest = match.group("name"), match.group("rest")
    rest = re.sub(r"\s*n\.b\..*$", "", rest).strip(" .,")
    phrases = [phrase.strip() for phrase in re.split(r"[,.]\s+", rest) if phrase.strip()]
    return _FIGURES[name](_Steps(name, phrases))
