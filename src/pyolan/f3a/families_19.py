"""F3A families, group 19: spins.

Conventions decided per family (check against the drawings at review):

- spin: the entry line, a spin that drops the nose to the vertical downline, a
  short vertical line and a 1/4 loop out in the entry direction (the drawings
  show the exit line leaving the way the entry line came). The spin direction is
  the pilot's choice (the builder's reversible spin). Whether the loop is pulled
  or pushed follows from the exit attitude, which follows from the turns: a whole
  number of turns leaves the canopy facing the entry direction, so a pull gives
  an exit in the entry attitude; a half turn more gives the opposite attitude
  ("2 1/2 turn spin" exits inverted, "inverted exit" or "inverted entry, upright
  exit" say so). The figure finishes lower than it started, by definition.
- "half roll exit": a half roll on the exit line, after the 1/4 loop, with the
  line the rules put between a roll that ends a figure and its neighbour.
- "2 turn opposite spin": decided 2026-11-19 as one turn one way followed by one
  turn the other, without recovering in between (the builder's spin has no drop
  after another spin and no recovery before one). Both directions are in one
  mirror option so they stay opposite. This is a reading of the words: the drawing
  shows two mirrored spin symbols, each of which may stand for two turns.
- "2 1/4 turn spin, 1/4 loop with 1/4 roll integrated": the spin leaves the
  canopy facing sideways, so the 1/4 loop is flown in knife-edge, and the 1/4 roll
  integrated in it brings the wings level over the whole loop (the roll's direction
  sets the exit attitude, which the description states). The spin direction, the
  knife-edge loop and the roll are one mirror option, since the canopy side after
  the spin decides the loop's direction.
"""

from __future__ import annotations

import re
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll, Spin

from .families import Modifiers, family  # isort: skip

# the turns of each spin family: (turns, opposite). An opposite spin is flown as
# half the turns one way and half the other.
_SPINS: dict[str, tuple[Fraction, bool]] = {
    "2 1/2 turn spin": (Fraction(5, 2), False),
    "three turn spin": (Fraction(3), False),
    "2 turn opposite spin": (Fraction(2), True),
    "two turn opposite spin": (Fraction(2), True),
    "2 1/4 turn spin": (Fraction(9, 4), False),
}

_ATTITUDE = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}
_EXIT_RE = re.compile(r"^(?:(?P<a>upright|inverted) exit|exit (?P<b>upright|inverted))$")
_ENTRY_RE = re.compile(r"^(?:(?P<a>upright|inverted) entry|entry (?P<b>upright|inverted))$")
_QUARTER = "1/4 roll"


@family(*_SPINS)
def spin(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    turns, opposite = _SPINS[name]
    entry, exit_ = mods.entry, mods.exit
    entry_given = False
    half_roll_exit = loop = integrated = False
    # "1/4 loop with 1/4 roll integrated. Entry upright. Exit upright" is one phrase
    for phrase in (part.strip() for text in phrases for part in text.split(".")):
        if not phrase:
            continue
        if match := _EXIT_RE.match(phrase):
            attitude = _ATTITUDE[match.group("a") or match.group("b")]
            if exit_ is not None and exit_ != attitude:
                raise F3AParseError(f"{name}: the exit attitude is given twice")
            exit_ = attitude
        elif match := _ENTRY_RE.match(phrase):
            attitude = _ATTITUDE[match.group("a") or match.group("b")]
            if entry_given or (attitude != entry and entry != p.Orientation.UPRIGHT):
                raise F3AParseError(f"{name}: the entry attitude is given twice")
            entry, entry_given = attitude, True
        elif phrase == "half roll exit" and name == "2 1/2 turn spin" and not half_roll_exit:
            half_roll_exit = True
        elif phrase == "1/4 loop" and name == "2 1/4 turn spin" and not loop:
            loop = True
        elif phrase == "1/4 roll integrated" and name == "2 1/4 turn spin" and not integrated:
            integrated = True
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
    if (name == "2 1/4 turn spin") != (loop and integrated) or loop != integrated:
        raise F3AParseError(f"{name}: expected a 1/4 loop with a 1/4 roll integrated")
    if name == "2 1/4 turn spin" and exit_ is None:
        raise F3AParseError(f"{name}: the exit attitude is not given")

    # a spin whose direction is not tied to anything else is the builder's reversible one
    if opposite:
        spins = [Spin(turns, linked=True), Spin(-turns, linked=True)]
    else:
        spins = [Spin(turns, linked=integrated)]
    clauses: list[Clause] = [Entry(entry), *spins, Line(frozenset({Fraction(3, 4)}), label="downline")]
    if integrated:
        quarter = OlanRoll(_QUARTER, require_roll(_QUARTER).roll_arr)
        clauses.append(Loop(Fraction(1, 4), sense=1, knife_edge=True, roll=quarter, integrated=True))
    else:
        clauses.append(Loop(Fraction(1, 4), sense=1))
    if half_roll_exit:
        clauses.append(Roll(require_roll("half roll")))
    clauses.append(Exit(exit_))
    return clauses
