"""F3A families, group J: top hat turnarounds.

The group J figures are turnaround versions of the group 17 top hat: they exit back
the way they came. This module wraps the registered ``top hat`` family so that
``Modifiers.forward`` False (a lettered group) is built here and the group 17 centre
top hat is untouched.

Conventions decided per family (checked against the USG drawings):

- two shapes, both of the same four 1/4 loops, two vertical lines (one shared
  ``line_length``, so the figure finishes at its entry height) and a horizontal line
  between them, with the exit loop flown back. The drawings use one shape or the
  other for different entries, and nothing in the words says which:
  - forward top line (J.1-J.10, the plain "Top hat, <roll> up, <roll> down" from
    the bottom): entry, 1/4 loop up, the upline, 1/4 loop, the top line flown on
    in the direction of travel, 1/4 loop, the downline and a 1/4 loop out the other
    way (corners 1/4, -1/4, -1/4, -1/4: the group 17 top hat with its exit turned
    round). The drawings show this top line oblique for the 1/4 and 3/4 rolls (the
    wings are vertical on it).
  - back top line (every other entry that is implemented: "from top" J.11-J.16,
    "from upright|inverted" J.17-J.20 and J.26-J.29, "from top upright|inverted"
    J.22-J.25 and J.30-J.33, the spin entries J.38-J.45): the top line (bottom line
    from top) is flown back, towards where the figure started, so three corners turn
    one way and the exit loop the other (corners 1/4, 1/4, 1/4, -1/4). From top is the
    mirror image about the entry height.
- ``<roll> up`` / ``<roll> down``: a roll centred on the vertical line flown that way
  (from the bottom the up line is first, from the top the down line is first). The
  rolls are the pilot's choice of direction, so only their quarter-roll signs that
  decide the knife-edge side are linked, in one mirror option together with the
  knife-edge loops: the stated exit attitude fixes the relative direction of the
  second roll. When no exit is stated (J.1-J.16) the exit is upright, as the
  catalogue metadata says (so J.2, with an inverted entry, rolls the other way round
  from J.1).
- ``three consecutive 1/4 rolls`` and ``four consecutive 1/4 rolls`` are one roll
  with a stop every quarter.
- ``<n> turn spin entry`` (J.38-J.45, from top): the spin takes the place of the
  entry corner and its nose drop, followed by the vertical downline, the two bottom
  corners and the up line with the roll. A spin of whole turns leaves the canopy facing the
  entry direction, so the corners that follow (and the exit) leave the figure inverted
  without a roll (as in group 19); 2 1/4 turns leave the wings vertical, so the
  corners are knife-edge and the spin direction is one mirror option with them.
  The up line is lengthened by the drop of the spin so that the figure finishes at the
  height it started.

J.34-J.37 ("1/2 roll up, snap roll down, exit upright"): over a half loop top a full
snap and a half roll leave the figure inverted whatever the direction, so these are
built with a flat top line (two 1/4 corners), which gives the stated upright exit. The
drawings change attitude at the snap instead, as a half snap would (open question).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import parse_amount, require_roll
from .steps import DOWN_LINE, UP, Clause, Entry, Exit, Line, Loop, Roll, Spin

from .families import FAMILIES, Modifiers  # isort: skip

_ATTITUDE = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}
_ENTRY_RE = re.compile(r"^(?:from )?(?P<att>upright|inverted)$")
_EXIT_RE = re.compile(r"^(?:exit (?P<a>upright|inverted)|(?P<b>upright|inverted) exit)$")
_UPDOWN_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")
_SPIN_RE = re.compile(r"^(?P<turns>\d+(?: \d+/\d+)?) turn spin entry$")


@dataclass
class _Description:
    entry: p.Orientation
    exit: p.Orientation | None
    rolls: dict[str, OlanRoll]
    spin: Fraction | None
    entry_stated: bool


def _read(name: str, mods: Modifiers, phrases: list[str]) -> _Description:
    entry, exit_ = mods.entry, mods.exit
    entry_stated = False
    rolls: dict[str, OlanRoll] = {}
    spin: Fraction | None = None
    for phrase in phrases:
        if match := _ENTRY_RE.match(phrase):
            if entry_stated or mods.entry != p.Orientation.UPRIGHT:
                raise F3AParseError(f"{name}: the entry attitude is given twice")
            entry, entry_stated = _ATTITUDE[match.group("att")], True
        elif match := _EXIT_RE.match(phrase):
            attitude = _ATTITUDE[match.group("a") or match.group("b")]
            if exit_ is not None:
                raise F3AParseError(f"{name}: the exit attitude is given twice")
            exit_ = attitude
        elif match := _SPIN_RE.match(phrase):
            if spin is not None:
                raise F3AParseError(f"{name}: two spins")
            spin = parse_amount(match.group("turns"))
        elif (match := _UPDOWN_RE.match(phrase)) and match.group("dir") not in rolls:
            rolls[match.group("dir")] = require_roll(match.group("roll"))
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
    return _Description(entry, exit_, rolls, spin, entry_stated)


def _forward_top(mods: Modifiers, desc: _Description) -> bool:
    """Which of the two drawn shapes (see the module docstring)."""
    if mods.start is None and not desc.entry_stated:
        return True  # J.1-J.10
    # J.34-J.37: a half roll on one line and a snap roll on the other, flat top line
    kinds = sorted(
        (r.roll_arr[0].kind, abs(r.total())) for r in desc.rolls.values() if len(r.roll_arr) == 1
    )
    return len(desc.rolls) == 2 and kinds == [("roll", 0.5), ("snap", 1.0)]


def _vertical_length(rolls: dict[str, OlanRoll]) -> str | None:
    """A builder length for both vertical lines, when a roll needs more than ``line_length``.

    A roll of three or four stops and its pads are longer than the default line (a
    3/4 roll is not), so the lines would be unequal and the figure would finish above
    its entry height (as for Figure M, ``families_15_16``).
    """
    stops = max((len(r.roll_arr) for r in rolls.values()), default=0)
    return "(2*line_length)" if stops >= 4 else "(1.5*line_length)" if stops == 3 else None


def top_hat_turnaround(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    desc = _read(name, mods, phrases)
    top = mods.start == "top"
    if mods.start not in (None, "top") or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: a start at {mods.start!r} is not supported")
    sense = -1 if top else 1
    first, second = ("down", "up") if top else ("up", "down")
    exit_ = desc.exit if desc.exit is not None else p.Orientation.UPRIGHT

    if desc.spin is not None:
        return _spin_entry(name, mods, desc, exit_)
    if set(desc.rolls) != {"up", "down"}:
        raise F3AParseError(f"{name}: expected a roll up and a roll down, got {phrases!r}")

    def theta(n: int, signs: list[int]) -> frozenset[Fraction]:
        return frozenset({sum((Fraction(s, 4) for s in signs[:n]), Fraction(0)) % 1})

    forward_top = _forward_top(mods, desc)
    signs = [sense, -sense, -sense] if forward_top else [sense, sense, sense]
    clauses: list[Clause] = [Entry(desc.entry)]
    for leg in range(1, 4):
        clauses.append(Loop(Fraction(1, 4), sense=signs[leg - 1]))
        length = _vertical_length(desc.rolls) if leg != 2 else None
        clauses.append(Line(theta(leg, signs), label=f"leg {leg}", length=length))
        if leg == 1:
            clauses.append(Roll(desc.rolls[first]))
        elif leg == 3:
            clauses.append(Roll(desc.rolls[second]))
    clauses.append(Exit(exit_))
    return clauses


def _spin_entry(name: str, mods: Modifiers, desc: _Description, exit_: p.Orientation) -> list[Clause]:
    if mods.start != "top" or set(desc.rolls) != {"up"}:
        raise F3AParseError(f"{name}: a spin entry is from the top, with a roll up")
    # a spin of whole turns leaves the wings level, the quarter turn leaves them vertical
    linked = desc.spin % 1 != 0
    length = _vertical_length(desc.rolls)
    return [
        Entry(desc.entry),
        Spin(desc.spin, linked=linked),
        Line(DOWN_LINE, label="downline", length=length),
        Loop(Fraction(1, 4), sense=-1),
        Line(frozenset({Fraction(1, 2)}), label="bottom line"),
        Loop(Fraction(1, 4), sense=-1),
        Line(UP, label="upline", length=length),
        Roll(desc.rolls["up"]),
        Exit(exit_),
    ]


def _wrap_top_hat() -> None:
    for i, fam in enumerate(FAMILIES):
        if fam.name == "top hat":
            centre = fam.build

            def build(name, mods, phrases, centre=centre):
                return centre(name, mods, phrases) if mods.forward else top_hat_turnaround(name, mods, phrases)

            FAMILIES[i] = replace(fam, build=build)
            return
    raise RuntimeError("the group 17 top hat is not registered")


_wrap_top_hat()
