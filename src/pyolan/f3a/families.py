"""Figure families: a name, its shape and where its rolls go.

Each family turns the modifier phrases left after the shared modifiers (start
height, entry and exit attitude) into clauses. A family must use every phrase
it is given or raise an error that names the phrase.

Conventions decided per family (check against the drawings at review):

- loop (01): the loop starts at the bottom unless ``from top``. A rolling loop's
  roll is integrated through the whole loop; any other roll in it takes 90
  degrees centred on the apex (or nadir). A knife-edge loop has a 1/4 roll on the entry
  and exit lines and exits in its entry attitude.
- square loop on corner (06): legs are numbered in flight order; ``four
  <roll>s`` puts one in each leg. The diamond keeps its shape after half rolls
  (the following corners are pushed).
- rolling circle (22): one level 360 degree turn, the rolls spread over it,
  towards the inside or the outside of the turn ("inside" rolls the way the turn
  goes: left turn, left roll; "outside" the other way). The drawing does not say
  which way the circle turns, so both are allowed: a mirror option, the first the
  circle away from the pilot (a left turn for a figure entering with the pilot on its
  right, the way the figure is built), the second toward the pilot, which is usually
  silly (decided 2026-11-20, A4 review). Both the turn and the roll flip together.
- two loops (02) and avalanche (03): consecutive loops in one sense. A roll
  "at top" (from bottom) or "at bottom" (from top) is in the loop's far point
  and takes 90 degrees centred on it, as in the loop.
- triangular loop (04): one loop in the shape of a triangle with 45 degree
  legs. It starts at the apex (corners 1/8, 3/8, 3/8, 1/8, the base flown
  backwards) or on the base (3/8, 1/4, 3/8: the base is the entry and exit
  line). Starting at the apex the base closes the figure (sqrt(2)*line_length, user
  decision 2026-11-22, not compared with the legs); starting on the base the entry
  and exit lines are the base. The base is opposite the start height unless "(base at ...)" says
  otherwise. A lone roll goes on the base, plural rolls ("1/2 rolls") on every
  leg and "in 45 degree legs" on the two sloping legs.
- a roll that starts or ends a figure is separated from its neighbouring loop by
  a line (see steps.figure_ndmps): 20 m by default, a comparison parameter shared
  by those lines, not tied to the figure's other lines.
- square loop (05): four quarter loops in one sense. Legs are numbered in
  flight order (up or down, far side, down or up, exit line); plural rolls go
  on all four and "over top" or "at bottom" on the far side.
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
    start: str | None = None  # "top", "middle" or "bottom"
    first: str | None = None  # from the middle: which half goes first, "top" or "bottom"
    entry_form: bool = False  # written "(top entry)" rather than "from top"
    forward: bool = True  # a centre figure (numbered group); lettered groups are turnarounds


@dataclass(frozen=True)
class Family:
    name: str  # normalised family name, as it starts the description
    build: Callable[[str, Modifiers, list[str]], list[Clause]]
    # accepts a start at the middle, "top first" and the "(top entry)" form
    entry_heights: bool = False


FAMILIES: list[Family] = []


def family(*names: str, entry_heights: bool = False):
    def register(build):
        for name in names:
            FAMILIES.append(Family(name, build, entry_heights))
        return build

    return register


def _sense(mods: Modifiers) -> int:
    return -1 if mods.start == "top" else 1


_LOCATION_RE = re.compile(r"^(?P<roll>.+?) (?P<where>on top|at top|at bottom)$")


def _far_point(name: str, where: str, mods: Modifiers) -> None:
    """Check a roll's "top" or "bottom" is the far point of the loop."""
    far = "bottom" if mods.start == "top" else "top"
    if where.split()[-1] != far:
        raise F3AParseError(f"{name}: a roll {where} of a loop from {mods.start or 'bottom'}")


def _polygon(
    mods: Modifiers,
    sense: int,
    corners: list[Fraction],
    rolls: dict[int, OlanRoll],
    knife_edge: bool = False,
    lengths: dict[int, str] | None = None,
) -> list[Clause]:
    """A loop of straight legs joined by corner loops, all turning one way.

    Legs are numbered from 1 between the corners; the line after the last
    corner is the leg after the last one. Rolls are given by leg number, and
    lengths gives a builder expression (such as "2*loop_radius") for the legs
    that must have a particular length for the figure to close.
    """
    lengths = lengths or {}
    quarter = OlanRoll("1/4 roll", require_roll("1/4 roll").roll_arr)
    clauses: list[Clause] = [Entry(mods.entry)]
    if knife_edge:
        clauses.append(Roll(quarter))
    theta = Fraction(0)
    for i, amount in enumerate(corners, start=1):
        clauses.append(Loop(amount, sense=sense, knife_edge=True if knife_edge else None))
        theta = (theta + amount * sense) % 1
        if i < len(corners) or i in rolls:
            clauses.append(
                Line(
                    frozenset({theta}),
                    knife_edge=True if knife_edge else None,
                    label=f"leg {i}",
                    length=lengths.get(i),
                )
            )
        if i in rolls:
            clauses.append(Roll(rolls[i]))
    unused = set(rolls) - set(range(1, len(corners) + 1))
    if unused:
        raise F3AParseError(f"no leg {sorted(unused)} to roll in")
    if knife_edge:
        clauses.append(Roll(quarter))
    clauses.append(Exit(mods.exit if mods.exit is not None else mods.entry if knife_edge else None))
    return clauses


def _is_plural(phrase: str) -> bool:
    return phrase.endswith(" rolls") or phrase.endswith(" snaps")


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
    clauses.append(
        Loop(
            Fraction(1),
            sense=sense,
            knife_edge=knife_edge,
            roll=roll,
            integrated=name == "rolling loop",
        )
    )
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
        Turn(Fraction(1), roll=roll, inside=match.group("io") == "inside", left=True),
        Exit(mods.exit),
    ]


_FIRST_RE = re.compile(r"^(?P<roll>.+?) first (?P<where>top|bottom)$")
_SECOND_RE = re.compile(r"^(?P<roll>.+?) second$")


@family("two loops")
def two_loops(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    sense = _sense(mods)
    rolls: list[OlanRoll] = []
    for phrase in phrases:
        if match := _LOCATION_RE.match(phrase):
            if rolls:
                raise F3AParseError(f"{name}: unexpected {phrase!r}")
            _far_point(name, match.group("where"), mods)
            rolls = [require_roll(match.group("roll"))] * 2
        elif match := _FIRST_RE.match(phrase):
            if rolls:
                raise F3AParseError(f"{name}: unexpected {phrase!r}")
            _far_point(name, match.group("where"), mods)
            rolls = [require_roll(match.group("roll"))]
        elif (match := _SECOND_RE.match(phrase)) and len(rolls) == 1:
            rolls.append(require_roll(match.group("roll")))
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
    if len(rolls) != 2:
        raise F3AParseError(f"{name}: expected a roll in each loop, got {phrases!r}")
    return [
        Entry(mods.entry),
        Loop(Fraction(1), sense=sense, roll=rolls[0]),
        Loop(Fraction(1), sense=sense, roll=rolls[1]),
        Exit(mods.exit),
    ]


@family("avalanche")
def avalanche(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if len(phrases) != 1:
        raise F3AParseError(f"{name}: expected one snap, got {phrases!r}")
    roll = require_roll(phrases[0])
    if not all(r.kind == "snap" for r in roll.roll_arr):
        raise F3AParseError(f"{name}: expected a snap, got {phrases[0]!r}")
    return [Entry(mods.entry), Loop(Fraction(1), sense=_sense(mods), roll=roll), Exit(mods.exit)]


TRIANGLE_CLOSING_LENGTH = "(line_length*1.4142135623730951)"
_BASE_RE = re.compile(r"^\(base at (?P<base>top|bottom)\)$")
_LEGS_45_RE = re.compile(r"^(?P<roll>.+?) in 45 (?:degree )?legs$")
_ON_BASE_RE = re.compile(r"^(?P<roll>.+?) (?:on|at) (?P<where>horizontal leg|top|bottom)$")


@family("triangular loop", "knife-edge triangular loop")
def triangular_loop(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    knife_edge = name.startswith("knife-edge")
    start = mods.start or "bottom"
    base = None
    spec: list[str] = []
    for phrase in phrases:
        if match := _BASE_RE.match(phrase):
            base = match.group("base")
        else:
            spec.append(phrase)
    base = base or ("bottom" if start == "top" else "top")
    sense = _sense(mods)
    apex_start = base != start
    if knife_edge and (not apex_start or mods.start):
        raise F3AParseError(f"{name}: only the loop with its apex at the start is described")
    if apex_start:
        corners = [Fraction(1, 8), Fraction(3, 8), Fraction(3, 8), Fraction(1, 8)]
        base_leg, sloping = 2, (1, 3)
    else:
        corners = [Fraction(3, 8), Fraction(1, 4), Fraction(3, 8)]
        base_leg, sloping = None, (1, 2)
    rolls: dict[int, OlanRoll] = {}

    def put(legs: tuple[int | None, ...], roll: OlanRoll, phrase: str) -> None:
        for leg in legs:
            if leg is None or leg in rolls:
                raise F3AParseError(f"{name}: {phrase!r} has no leg to roll in")
            rolls[leg] = roll

    for phrase in spec:
        if match := _LEGS_45_RE.match(phrase):
            put(sloping, require_roll(match.group("roll")), phrase)
        elif match := _ON_BASE_RE.match(phrase):
            where = match.group("where")
            if where != "horizontal leg" and where != base:
                raise F3AParseError(f"{name}: the base is at the {base}, not {where!r}")
            put((base_leg,), require_roll(match.group("roll")), phrase)
        elif _is_plural(phrase):
            if not apex_start:
                raise F3AParseError(f"{name}: unexpected {phrase!r}")
            put((1, 2, 3), require_roll(phrase), phrase)
        elif (roll := parse_roll(phrase)) is not None:
            put((base_leg,), roll, phrase)
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
    # The horizontal side of a triangle that starts at its apex closes the figure
    # (user decision 2026-11-22): the two 45 degree legs rise and fall line_length
    # each, the corner radii cancel in x, so it is sqrt(2)*line_length long. An
    # expression has no comparison collector, so it is not compared with the legs.
    lengths = {2: TRIANGLE_CLOSING_LENGTH} if apex_start else None
    return _polygon(mods, sense, corners, rolls, knife_edge, lengths)


_SIDE_RE = re.compile(r"^(?P<roll>.+?) (?P<where>over top|at top|at bottom)$")


@family("square loop")
def square_loop(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    rolls: dict[int, OlanRoll] = {}
    for phrase in phrases:
        if match := _SIDE_RE.match(phrase):
            _far_point(name, match.group("where"), mods)
            rolls[2] = require_roll(match.group("roll"))
        elif _is_plural(phrase):
            roll = require_roll(phrase)
            rolls.update({leg: roll for leg in (1, 2, 3, 4)})
        else:
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
    return _polygon(mods, _sense(mods), [Fraction(1, 4)] * 4, rolls)


def find_family(text: str) -> tuple[Family, str]:
    """The family whose name starts the text (longest first) and the rest."""
    for fam in sorted(FAMILIES, key=lambda f: -len(f.name)):
        if text == fam.name or text.startswith(fam.name + " ") or text.startswith(fam.name + ","):
            return fam, text[len(fam.name):]
    raise F3AParseError(f"no figure family matches {text!r}")


# Families of later groups live in their own modules (they register themselves
# with @family on import, and use the helpers above).
from . import families_07_09, families_10, families_11_12, families_13_14, families_15_16, families_17_18, families_19, families_20, families_21  # noqa: E402,F401
from . import (  # noqa: E402,F401
    families_23,
    families_24_25,
    families_27_30,
    families_a_c_d,
    families_e,
    families_f,
    families_g_h,
    families_j,
    families_k,
    families_l_m,
    families_n,
    families_p_q,
)
