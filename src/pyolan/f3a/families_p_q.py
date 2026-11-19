"""F3A families, lettered groups P (vertical 5/8 loop) and Q (almost 8).

Conventions decided per family (checked against the USG drawings):

- vertical 5/8 loop (P): a turnaround. Entry line, a 1/4 loop up into a vertical
  upline (``from top``: down into a downline), the snap on the vertical line, a 5/8
  loop that turns on in the same sense (so the path leaves it at 45 degrees, back
  towards the entry side), a 45 degree line with the second roll, and a 3/8 loop the
  other way onto the exit line, flying back the way the figure came. The loops all
  have the figure's one radius; the 45 degree line is a ``line_length`` and the vertical
  ``(0.7071*line_length)+(1.4142*loop_radius)``, which makes the figure finish at the
  height it started at (the drawings show the exit line a little above the entry:
  an open question, see the report). The rolls are centred on their lines.
  - ``snap-roll``, ``half roll`` | ``roll``: a full snap leaves the wings level, so
    the 5/8 loop is a plane loop pulled or pushed by the attitude; a half roll on the
    45 degree line makes the last loop pulled when the loops before were (exit in the
    entry attitude), a full roll makes it the other kind (exit the other way up).
  - ``3/4 snap-roll``, ``1/4 roll`` | ``1/4 half roll``: the 3/4 snap leaves the wings
    vertical, so the 5/8 loop is flown in knife-edge (the drawings dash-dot it), and
    the 1/4 roll puts the wings level again. "1/4 half roll" is read as a 1/4 roll
    (the drawings label both 1/4): it is the one that turns the figure over, the net
    roll of the snap and the quarter roll being a half roll. The snap and the quarter
    roll are one mirror option (the exit attitude decides their relative direction).
  - The USG descriptions of P.6 and P.12 (also the rulebook's) disagree with their drawings;
    the parser's ERRATA table corrects them (see the tests).
- almost 8 (Q): three half loops of one radius stacked in the vertical plane, so the
  figure is a vertical eight with one half loop missing (a turnaround). ``from
  bottom|top|middle <attitude>``, each half loop ``pulled`` or ``pushed`` (the words
  and the attitude decide which way it goes) with ``roll integrated`` (a full roll) or
  ``1/2 roll integrated`` spread over that half loop, and ``exit <height> <attitude>``.
  The start and exit heights are checked against the figure's geometry (the figure is
  4 radii high). Roll directions are the pilot's choice.
"""

from __future__ import annotations

import re
from fractions import Fraction

import schemas.positioning as p

from .errors import F3AParseError
from .rolls import is_quarter, require_roll
from .steps import DOWN_LINE, UP, Clause, Entry, Exit, Line, Loop, Roll, resolve

from .families import Modifiers, family  # isort: skip
from .families_a_c_d import _attitude_after, _exit_attitude  # isort: skip

_ATTITUDE = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}
_HEIGHT = {"bottom": p.Height.BTM, "middle": p.Height.MID, "top": p.Height.TOP}

QUARTER = Fraction(1, 4)

# The figure finishes at the height it started at when the vertical line is
# 0.7071*D + 1.4142*r (D the 45 degree line, r the loop radius: the 1/4 and 3/8 corners
# and the 5/8 loop add 1.4142 r). The 45 degree line is one line_length, which holds
# a half or a full roll and its pads at the default radius. The vertical's length is
# also given in the line units steps.py uses for heights (a loop radius is 0.5).
VERTICAL = "((0.7071*line_length)+(1.4142*loop_radius))"
VERTICAL_UNITS = 0.7071 + 1.4142 * 0.5

_QUARTER_HALF_RE = re.compile(r"^1/4 half roll$")


@family("vertical 5/8 loop")
def vertical_five_eighth_loop(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start not in (None, "top") or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: a start at {mods.start!r} is not supported")
    # 'exit inverted' is a shared modifier, so only 'exit upright' can be left
    if len(phrases) not in (3, 4):
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    start, snap, second, *rest = phrases
    attitude = _attitude_after(name, mods, start)
    exit_attitude = _exit_attitude(name, mods, rest)
    snap_roll = require_roll(snap)
    if not all(r.kind == "snap" for r in snap_roll.roll_arr):
        raise F3AParseError(f"{name}: expected a snap, got {snap!r}")
    knife_edge = is_quarter(snap_roll)
    if not knife_edge and abs(snap_roll.total()) % 1:
        raise F3AParseError(f"{name}: unexpected snap {snap!r}")
    # "1/4 half roll" is the quarter roll that turns the figure over (see above)
    second_roll = require_roll("1/4 roll" if _QUARTER_HALF_RE.match(second) else second)
    if is_quarter(second_roll) != knife_edge:
        raise F3AParseError(f"{name}: {snap!r} followed by {second!r} does not leave the wings level")
    sense = -1 if mods.start == "top" else 1
    vertical = UP if sense == 1 else DOWN_LINE
    diagonal = frozenset({(next(iter(vertical)) + Fraction(5, 8) * sense) % 1})
    return [
        Entry(attitude),
        Loop(QUARTER, sense=sense),
        Line(vertical, label="vertical line", length=VERTICAL, units=VERTICAL_UNITS),
        Roll(snap_roll),
        Loop(Fraction(5, 8), sense=sense, knife_edge=knife_edge),
        Line(diagonal, label="45 degree line"),
        Roll(second_roll),
        Loop(Fraction(3, 8), sense=-sense),
        Exit(exit_attitude),
    ]


_HALF_LOOP_RE = re.compile(r"^(?:half (?P<a>pulled|pushed) loop|(?P<b>pulled|pushed) half loop)$")
_INTEGRATED_RE = re.compile(r"^(?P<roll>.+?) integrated$")
_EXIT_RE = re.compile(r"^exit (?P<height>bottom|middle|top) (?P<att>upright|inverted)$")


@family("almost 8.", entry_heights=True)
def almost_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.first or mods.entry_form or mods.start is None:
        raise F3AParseError(f"{name}: expected 'from bottom|middle|top <attitude>'")
    if len(phrases) < 4:
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    attitude = _ATTITUDE.get(phrases[0])
    if attitude is None:
        raise F3AParseError(f"{name}: expected the entry attitude, got {phrases[0]!r}")
    *steps, last = phrases[1:]
    if not (exit_match := _EXIT_RE.match(last)):
        raise F3AParseError(f"{name}: expected 'exit <height> <attitude>', got {last!r}")
    clauses: list[Clause] = [Entry(attitude)]
    loops = 0
    for phrase in steps:
        if match := _HALF_LOOP_RE.match(phrase):
            clauses.append(Loop(Fraction(1, 2), pull=(match.group("a") or match.group("b")) == "pulled"))
            loops += 1
        elif (match := _INTEGRATED_RE.match(phrase)) and loops:
            loop = clauses[-1]
            if loop.roll is not None:
                raise F3AParseError(f"{name}: two rolls in one half loop ({phrase!r})")
            loop.roll, loop.integrated = require_roll(match.group("roll")), True
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
    if loops != 3:
        raise F3AParseError(f"{name}: expected three half loops, got {loops}")
    clauses.append(Exit(_ATTITUDE[exit_match.group("att")]))
    # the stated heights must be the ones the half loops reach
    (resolved,) = resolve(clauses, forward=False)
    for word, got, height in (
        ("from", resolved.entry_height, mods.start),
        ("exit", resolved.exit_height, exit_match.group("height")),
    ):
        if got != _HEIGHT[height]:
            raise F3AParseError(f"{name}: {word} {height} but the figure is at {got.name.lower()} there")
    return clauses
