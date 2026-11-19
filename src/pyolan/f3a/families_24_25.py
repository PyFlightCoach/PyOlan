"""F3A families, groups 24 (double key) and 25 (horizontal eight with rolls).

Conventions decided per family (checked against the USG drawings):

- double key (24): written step by step after the name and a colon. Entry line, a
  1/4 loop up into a vertical upline with a 3/4 point roll, a 5/8 knife-edge loop
  "towards the back" (against the direction of travel, path angle 1/4 to 7/8), a
  45 degree downline with a 3/4 roll, a 1/4 loop (pulled or pushed as the words say)
  onto a 45 degree upline with a 3/4 roll, a second 5/8 knife-edge loop towards the
  back (path angle 1/8 to 3/4), a vertical downline with a 3/4 point roll and a 1/4
  loop to the exit line. The loops all turn the same way, so the figure is a heart
  (two lobes either side of the verticals) as the drawings show, and it finishes
  at its entry height because the two verticals and the two 45 degree lines are each
  as long as one another (line_length). "pull" and "push" are read as the wing
  attitude at that loop, so the figure's own geometry gives the quarter roll
  directions: the 3/4 roll after a knife-edge loop makes the following loop a pull
  (upright) or a push (inverted). The two halves (3/4pt roll, knife-edge loop,
  3/4 roll) are independent mirror options, ``roll_option`` and ``roll_option_2``:
  inside a half the roll directions, the yaw of the loop and the attitude it
  leaves are tied together (Loop.group, Roll.group in steps.py).
- horizontal eight (25): two circles side by side in the vertical plane, as the
  drawings show them: entry line, a 3/4 loop up (the first circle, three quarters),
  a full loop the other way (the second circle, behind the first, tangent to it
  at the point where the first is flown downwards), the last quarter of the first
  circle, and the exit line. The second circle is flown clockwise and the first
  counter-clockwise or the reverse, as the entry attitude needs, so the loops are
  +3/4, -1, +1/4 as the entry is pulled. The rolls are whole rolls, spread over
  the loop piece they are in (``integrated``), "one roll integrated in each loop" is
  a full roll in the 3/4 loop and a full roll in the full loop, "two rolls" and
  "four rolls" two or four of them. The last 1/4 of the first circle has no roll
  (the roll of a circle that another circle interrupts cannot span both pieces).
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import DOWN_LINE, UP, VERTICAL, Clause, Entry, Exit, Line, Loop, Roll  # noqa: F401

import schemas.positioning as p  # isort: skip
from .families import Modifiers, family  # isort: skip

Q = Fraction(1, 4)
_UP_45 = frozenset({Fraction(1, 8)})
_DOWN_45 = frozenset({Fraction(7, 8)})

_ENTRY_RE = re.compile(r"^(?:from (?P<att>inverted|upright) )?(?P<pp>pull|push) into vertical upline$")
_ROLL_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")
_KE_LOOP_RE = re.compile(r"^5/8 knife-edge loop towards the back$")
_TURN_RE = re.compile(r"^(?P<pp>pull|push) into 45 degree upline$")
_EXIT_RE = re.compile(r"^(?P<pp>pull|push) to(?: exit (?P<att>upright|inverted))?$")


def _is_pull(word: str) -> bool:
    return word == "pull"


@family("double key:")
def double_key(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None or mods.entry != p.Orientation.UPRIGHT:
        raise F3AParseError(f"{name} unexpected modifiers (start {mods.start!r}, entry {mods.entry.name})")
    if len(phrases) != 9:
        raise F3AParseError(f"{name} expected nine steps, got {len(phrases)}: {phrases!r}")
    entry_p, roll1, loop1, roll2, turn, roll3, loop2, roll4, exit_p = phrases

    def roll_on(phrase: str, direction: str):
        match = _ROLL_RE.match(phrase)
        if not match or match.group("dir") != direction:
            raise F3AParseError(f"{name} expected a roll {direction}, got {phrase!r}")
        roll = require_roll(match.group("roll"))
        if roll.total() != 0.75:
            raise F3AParseError(f"{name} expected a 3/4 roll, got {phrase!r}")
        return roll

    if not (m := _ENTRY_RE.match(entry_p)):
        raise F3AParseError(f"{name} unexpected {entry_p!r}")
    attitude = p.Orientation.INVERTED if m.group("att") == "inverted" else p.Orientation.UPRIGHT
    entry_pull = _is_pull(m.group("pp"))
    for phrase in (loop1, loop2):
        if not _KE_LOOP_RE.match(phrase):
            raise F3AParseError(f"{name} unexpected {phrase!r}")
    if not (m := _TURN_RE.match(turn)):
        raise F3AParseError(f"{name} unexpected {turn!r}")
    turn_pull = _is_pull(m.group("pp"))
    if not (m := _EXIT_RE.match(exit_p)):
        raise F3AParseError(f"{name} unexpected {exit_p!r}")
    exit_att = m.group("att")
    if exit_att is None:
        # "push to exit inverted" lost its "exit inverted" to the shared modifier
        if mods.exit is None:
            raise F3AParseError(f"{name} unexpected {exit_p!r}")
        final = mods.exit
    elif mods.exit is not None:
        raise F3AParseError(f"{name} the exit attitude is given twice")
    else:
        final = p.Orientation.INVERTED if exit_att == "inverted" else p.Orientation.UPRIGHT
    exit_pull = _is_pull(m.group("pp"))
    # a pull or push is a statement about the wings, so it must agree with the attitude
    if entry_pull != (attitude == p.Orientation.UPRIGHT):
        raise F3AParseError(f"{name} a {'pull' if entry_pull else 'push'} into the upline from {attitude.name.lower()}")
    if exit_pull != (final == p.Orientation.UPRIGHT):
        raise F3AParseError(f"{name} a {'pull' if exit_pull else 'push'} to exit {final.name.lower()}")
    return [
        Entry(attitude),
        Loop(Q, sense=1, pull=entry_pull),
        Line(UP),
        Roll(roll_on(roll1, "up")),
        Loop(Fraction(5, 8), sense=1, knife_edge=True),
        Line(_DOWN_45),
        Roll(roll_on(roll2, "down")),
        Loop(Q, sense=1, pull=turn_pull),
        Line(_UP_45),
        Roll(roll_on(roll3, "up"), group=1),
        Loop(Fraction(5, 8), sense=1, knife_edge=True, group=1),
        Line(DOWN_LINE),
        Roll(roll_on(roll4, "down"), group=1),
        Loop(Q, sense=1, pull=exit_pull),
        Exit(final),
    ]


# ---------------------------------------------------------------- horizontal eight

_EIGHT_ROLLS_RE = re.compile(r"^(?P<roll>.+?) integrated in each loop$")


@family("horizontal eight")
def horizontal_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    if len(phrases) != 1 or not (match := _EIGHT_ROLLS_RE.match(phrases[0])):
        raise F3AParseError(f"{name}: expected '<rolls> integrated in each loop', got {phrases!r}")
    roll: OlanRoll = require_roll(match.group("roll"))
    if any(r.kind != "roll" or r.turns % 1 for r in roll.roll_arr) or len(roll.roll_arr) != 1:
        raise F3AParseError(f"{name}: expected whole rolls, got {match.group('roll')!r}")
    return [
        Entry(mods.entry),
        Loop(Fraction(3, 4), sense=1, roll=roll, integrated=True),
        Loop(Fraction(-1), sense=1, roll=roll, integrated=True),
        Loop(Q, sense=1),
        Exit(mods.exit),
    ]
