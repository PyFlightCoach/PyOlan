"""F3A families, group J: top hat turnarounds.

The group J figures are turnaround versions of the group 17 top hat: they exit back
the way they came. This module wraps the registered ``top hat`` family so that
``Modifiers.forward`` False (a lettered group) is built here and the group 17 centre
top hat is untouched.

Conventions decided per family (checked against the USG drawings; the cross-box line
decided by the owner in the catalogue review of 2026-11-21: "if it's cross box then you
can choose in or out, otherwise it needs to be as per the drawing"):

- every entry whose rolls on the verticals are odd quarters (J.1-J.33 and the 2 1/4 turn spin
  entries J.38-J.41) is an Option of two figures (owner, 2026-11-22: "do what the sequence layout
  does for cross-box figures"; the FlightAnalysis layout sizes the first, planar member and
  takes a later member that moves in depth as a depth correction: it copies the planar sizes,
  shares the planar exit and joins from an approach offset in Y):
  1. the in-plane top hat, the straight option, which sizes the figure. Its top line (bottom
     line from top) is flown on in the direction of travel for J.1-J.10 (corners 1/4, -1/4,
     -1/4, -1/4) and back towards where the figure started for the others (1/4, 1/4, 1/4,
     -1/4); the first roll and the knife-edge corners are one mirror option, the stated exit
     attitude fixing the second roll.
  2. the cross-box top hat. The drawings draw the top line (bottom line from top) obliquely,
     in perspective: it is flown across the box. Entry, 1/4 loop up into the upline (from
     top: down into the downline) with its roll, which leaves the wings vertical, a 1/4 loop
     out of the figure plane, the line across the box, a 1/4 loop into the downline (from
     top: the upline) with the second roll, which puts the wings level again, and a 1/4 loop
     out the way the figure came. The drawings dash the cross-box line (inverted), so its
     loops are pulled over the top and pushed under the bottom (``steps.CrossBox``). Whether
     the line goes in or out follows from the first roll's direction, the pilot's choice; the
     second roll's direction is linked to it in one mirror option by the stated exit
     attitude. The verticals share one length (so the figure finishes at its entry height).
  Both members leave in the same attitude and heading and at the same height.
- the other entries are drawn in the plane and are one figure, as drawn:
  - J.34-J.37 ("1/2 roll up, snap roll down, exit upright"): the wings stay level, so
    the top line (bottom line from top) is flown on in the direction of travel (corners
    1/4, -1/4, -1/4 and the exit loop). Over a half loop top a full snap and a half roll
    leave the figure inverted whatever the direction, so the top line is flat (two 1/4
    corners), which gives the stated upright exit (owner: right, 2026-11-21).
  - the whole-turn spin entries J.42-J.45: the bottom line is flown back, towards where
    the figure started.
- ``<roll> up`` / ``<roll> down``: a roll centred on the vertical line flown that way
  (from the bottom the up line is first, from the top the down line is first). When no
  exit is stated (J.1-J.16) the exit is upright, as the catalogue metadata says.
- ``three consecutive 1/4 rolls`` and ``four consecutive 1/4 rolls`` are one roll
  with a stop every quarter.
- ``<n> turn spin entry`` (J.38-J.45, from top): the spin takes the place of the
  entry corner and its nose drop, followed by the vertical downline, the bottom
  (an Option of in-plane and cross-box after 2 1/4 turns, which leave the wings vertical; in
  the plane after whole turns, which leave the figure inverted without a roll, as in group 19) and the
  up line with the roll. The up line is lengthened by the drop of the spin so that the
  figure finishes at the height it started.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import is_quarter, parse_amount, require_roll
from .steps import DOWN_LINE, UP, Clause, CrossBox, Entry, Exit, Line, Loop, Roll, Spin

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
    """Which of the two in-plane shapes (see the module docstring)."""
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


def top_hat_turnaround(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause] | list[list[Clause]]:
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

    length = _vertical_length(desc.rolls)

    def theta(n: int, signs: list[int]) -> frozenset[Fraction]:
        return frozenset({sum((Fraction(s, 4) for s in signs[:n]), Fraction(0)) % 1})

    forward_top = _forward_top(mods, desc)
    signs = [sense, -sense, -sense] if forward_top else [sense, sense, sense]
    in_plane: list[Clause] = [Entry(desc.entry)]
    for leg in range(1, 4):
        in_plane.append(Loop(Fraction(1, 4), sense=signs[leg - 1]))
        in_plane.append(Line(theta(leg, signs), label=f"leg {leg}", length=length if leg != 2 else None))
        if leg == 1:
            in_plane.append(Roll(desc.rolls[first]))
        elif leg == 3:
            in_plane.append(Roll(desc.rolls[second]))
    in_plane.append(Exit(exit_))
    if not is_quarter(desc.rolls[first]):
        return in_plane  # J.34-J.37: wings level on the top line, as drawn
    # the first roll leaves the wings vertical, so the drawings draw the top (bottom) line
    # across the box: the same figure as an Option, the in-plane top hat first (it sizes the
    # figure) and the cross-box one as a depth correction
    cross_box = [
        Entry(desc.entry),
        Loop(Fraction(1, 4), sense=sense),
        Line(UP if not top else DOWN_LINE, label="leg 1", length=length),
        Roll(desc.rolls[first]),
        CrossBox(pull=not top),
        Line(DOWN_LINE if not top else UP, label="leg 3", length=length),
        Roll(desc.rolls[second]),
        Exit(exit_),
    ]
    return [in_plane, cross_box]


def _spin_entry(name: str, mods: Modifiers, desc: _Description, exit_: p.Orientation) -> list[Clause] | list[list[Clause]]:
    if mods.start != "top" or set(desc.rolls) != {"up"}:
        raise F3AParseError(f"{name}: a spin entry is from the top, with a roll up")
    # a spin of whole turns leaves the wings level, the quarter turn leaves them vertical
    linked = desc.spin % 1 != 0
    length = _vertical_length(desc.rolls)
    in_plane_bottom: list[Clause] = [
        Loop(Fraction(1, 4), sense=-1),
        Line(frozenset({Fraction(1, 2)}), label="bottom line"),
        Loop(Fraction(1, 4), sense=-1),
    ]

    def figure(bottom: list[Clause]) -> list[Clause]:
        return [
            Entry(desc.entry),
            Spin(desc.spin, linked=linked),
            Line(DOWN_LINE, label="downline", length=length),
            *bottom,
            Line(UP, label="upline", length=length),
            Roll(desc.rolls["up"]),
            Exit(exit_),
        ]

    # 2 1/4 turns leave the wings vertical: the bottom line is cross-box on the drawing, so
    # the in-plane figure (it sizes) comes first and the cross-box one is the correction
    return [figure(in_plane_bottom), figure([CrossBox(pull=False)])] if linked else figure(in_plane_bottom)


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
