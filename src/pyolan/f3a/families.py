"""Figure families: a name, its shape and where its rolls go.

Each family turns the modifier phrases left after the shared modifiers (start
height, entry and exit attitude) into clauses. A family must use every phrase
it is given or raise an error that names the phrase.

Conventions decided per family (check against the drawings at review):

- loop (01): the loop starts at the bottom unless ``from top``. A roll in it is
  centred on the apex (or nadir). A knife-edge loop has a 1/4 roll on the entry
  and exit lines and exits in its entry attitude.
- square loop on corner (06): legs are numbered in flight order; ``four
  <roll>s`` puts one in each leg. The diamond keeps its shape after half rolls
  (the following corners are pushed).
- rolling circle (22): one level 360 degree turn, the rolls spread over it,
  towards the inside or the outside of the turn.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import AMOUNT, parse_amount, parse_roll, require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll, Turn


@dataclass
class Modifiers:
    """The modifiers every family shares."""

    entry: p.Orientation = p.Orientation.UPRIGHT
    exit: p.Orientation | None = None
    start: str | None = None  # "top" or "bottom"


@dataclass(frozen=True)
class Family:
    name: str  # normalised family name, as it starts the description
    build: Callable[[str, Modifiers, list[str]], list[Clause]]


FAMILIES: list[Family] = []


def family(*names: str):
    def register(build):
        for name in names:
            FAMILIES.append(Family(name, build))
        return build

    return register


def _sense(mods: Modifiers) -> int:
    return -1 if mods.start == "top" else 1


_LOCATION_RE = re.compile(r"^(?P<roll>.+?) (?P<where>on top|at top|at bottom)$")


@family("rolling loop", "knife-edge loop", "loop")
def loop(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    sense = _sense(mods)
    roll: OlanRoll | None = None
    for phrase in phrases:
        where = None
        if match := _LOCATION_RE.match(phrase):
            phrase, where = match.group("roll"), match.group("where")
        if roll is not None or (parsed := parse_roll(phrase)) is None:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
        if where is not None and (where == "at bottom") != (sense == -1):
            raise F3AParseError(f"{name}: a roll {where} of a loop from {mods.start or 'bottom'}")
        roll = parsed
    if name == "rolling loop" and roll is None:
        raise F3AParseError("rolling loop: the roll is missing")
    knife_edge = name == "knife-edge loop"
    quarter = OlanRoll("1/4 roll", require_roll("1/4 roll").roll_arr)
    clauses: list[Clause] = [Entry(mods.entry)]
    if knife_edge:
        clauses.append(Roll(quarter))
    clauses.append(Loop(Fraction(1), sense=sense, knife_edge=knife_edge, roll=roll))
    if knife_edge:
        clauses.append(Roll(quarter))
    clauses.append(Exit(mods.exit if mods.exit is not None else mods.entry if knife_edge else None))
    return clauses


_LEGS_RE = re.compile(r"^(?P<roll>.+?) in legs? (?P<legs>\d(?: (?:&|and) \d)*)$")
_EACH_RE = re.compile(rf"^(?P<count>{AMOUNT}) (?P<roll>.+)$")


@family("square loop on corner")
def square_loop_on_corner(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    legs: dict[int, OlanRoll] = {}
    for phrase in phrases:
        if match := _LEGS_RE.match(phrase):
            roll = require_roll(match.group("roll"))
            numbers = [int(n) for n in re.findall(r"\d", match.group("legs"))]
        elif (match := _EACH_RE.match(phrase)) and parse_amount(match.group("count")) == 4:
            roll = require_roll(match.group("roll"))
            numbers = [1, 2, 3, 4]
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
        for leg in numbers:
            if leg in legs or not 1 <= leg <= 4:
                raise F3AParseError(f"{name}: leg {leg} given twice or out of range")
            legs[leg] = roll
    sense = _sense(mods)
    clauses: list[Clause] = [Entry(mods.entry), Loop(Fraction(1, 8), sense=sense)]
    for leg in range(1, 5):
        clauses.append(Line(label=f"leg {leg}"))
        if leg in legs:
            clauses.append(Roll(legs[leg]))
        clauses.append(Loop(Fraction(1, 4) if leg < 4 else Fraction(1, 8), sense=sense))
    clauses.append(Exit(mods.exit))
    return clauses


_CIRCLE_RE = re.compile(r"^(?P<roll>.+?) (?P<io>inside|outside)$")


@family("rolling circle")
def rolling_circle(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None:
        raise F3AParseError(f"{name}: no start height expected")
    if len(phrases) != 1 or not (match := _CIRCLE_RE.match(phrases[0])):
        raise F3AParseError(f"{name}: expected '<rolls> inside|outside', got {phrases!r}")
    roll = require_roll(match.group("roll"))
    return [
        Entry(mods.entry),
        Turn(Fraction(1), roll=roll, inside=match.group("io") == "inside"),
        Exit(mods.exit),
    ]


def find_family(text: str) -> tuple[Family, str]:
    """The family whose name starts the text (longest first) and the rest."""
    for fam in sorted(FAMILIES, key=lambda f: -len(f.name)):
        if text == fam.name or text.startswith(fam.name + " ") or text.startswith(fam.name + ","):
            return fam, text[len(fam.name):]
    raise F3AParseError(f"no figure family matches {text!r}")
