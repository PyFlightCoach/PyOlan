"""This module handles olan roll strings.
The ORoll class handles a single element, either a roll, snap or spin. This could be a single point of a point roll.
The OlanRoll class handles the entire combination, so all the points of a point roll.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal

import numpy as np
import schemas.positioning as p

from .errors import OlanParseError


# Map olan roll strings onto
olan_rolls = {k: np.array(v) for k, v in {
    "1": [1],
    "2": [0.5],
    "22": [0.5] * 2,
    "32": [0.5] * 3,
    "42": [0.5] * 4,
    "3": [0.75],
    "4": [0.25],
    "24": [0.25] * 2,
    "34": [0.25] * 3,
    "44": [0.25] * 4,
    "54": [0.25] * 5,
    "64": [0.25] * 6,
    "74": [0.25] * 7,
    "84": [0.25] * 8,
    "5": [1.25],
    "6": [1.5],
    "7": [7 / 4],
    "8": [0.125] * 2,
    "48": [0.125] * 4,
    "68": [0.125] * 6,
    "88": [0.125] * 8,
    "9": [2],
}.items()}


# One roll: an optional OLAN roll number and an optional snap or spin letter
# ("2", "24", "1f", "3if", "5s", "f"). Rolls are separated by ";" (same direction)
# or "," (opposite direction); OpenAero also reads rolls written one after another
# with no separator ("f2": a snap, then a half roll the same way).
oroll_re = re.compile(r"(?P<num>[1-9][248]?)?(?P<kind>if|is|f|s)?")


def _roll_pieces(piece: str) -> list[tuple[str | None, str | None]]:
    """[(number, kind)] for a piece between separators; every character is used."""
    out = []
    pos = 0
    while pos < len(piece):
        res = oroll_re.match(piece, pos)
        if res is None or res.end() == pos or (res["num"] and res["num"] not in olan_rolls):
            raise OlanParseError(f'"{piece}" is not an OLAN roll')
        out.append((res["num"], res["kind"]))
        pos = res.end()
    return out


@dataclass
class ORoll:
    kind: Literal["roll", "snap", "spin"]
    turns: float
    negative: bool = False
    # which written roll it comes from: the points of "24" share one piece, the
    # two quarter rolls of "4;4" have two (F14). The geometry is the same, so it
    # is not compared; the Aresti numbers and K are not the same.
    piece: int = field(default=0, compare=False)

    def __repr__(self):
        return f"{self.turns}{'i' if self.negative else ''}{dict(roll='', snap='f', spin='s')[self.kind]}"

    @property
    def pfc_char(self):
        return dict(roll="r", snap="s", spin="-")[self.kind]


def ro(turns: float) -> ORoll:
    return ORoll("roll", turns)


def sn(turns: float, negative: bool) -> ORoll:
    return ORoll("snap", turns, negative)


def spi(turns: float, negative: bool) -> ORoll:
    return ORoll("spin", turns, negative)


def create_roll(rollchars: str, turns: float) -> ORoll:
    match rollchars:
        case "f":
            return sn(turns, False)
        case "if":
            return sn(turns, True)
        case "s":
            return spi(turns, False)
        case "is":
            return spi(turns, True)
        case _:
            return ro(turns)


@dataclass
class OlanRoll:
    rawroll: str
    roll_arr: list[ORoll]

    def turns(self) -> list[float]:
        return [r.turns for r in self.roll_arr]

    def total(self) -> float:
        return sum(self.turns())

    def angles(self) -> list[float]:
        res = p.r(self.turns())
        return res if len(res) > 1 else res[0]

    def pfc_roll(self) -> list[float] | str | float:
        roll_arr = np.array(self.turns())
        if (
            len(roll_arr) > 1
            and np.all(roll_arr == roll_arr[0])
            and np.all(np.array([r.kind for r in self.roll_arr]) == "roll")
        ):
            return f"{len(roll_arr)}x{int(1 / roll_arr[0])}"
        else:
            return self.angles()

    def rolltypes(self) -> list[str]:
        rtypes = "".join([r.pfc_char for r in self.roll_arr])
        if len(rtypes) * "r" == rtypes:
            return "roll"
        elif len(rtypes) * "s" == rtypes:
            return "snap"
        elif len(rtypes) * "-" == rtypes:
            return "spin"
        else:
            return rtypes

    def parse(data: str) -> OlanRoll | None:
        """Read a roll string. Every piece is used; one that is not an OLAN roll
        raises OlanParseError. Catalogue slot markers (_ & $) are empty slots."""
        if not len(data):
            return None
        if not re.sub(r"[_&$]", "", data):
            return OlanRoll(data, [])  # a marker-only slot is an empty slot
        data = re.sub(r"[_&$]", "", data)
        rolls = []
        rollarr = [";"] + re.split(r"(;|,)", re.sub(r"^(;|,)", "", data))
        last_direction = 1
        piece = 0
        for direction, roll in zip(rollarr[::2], rollarr[1::2]):
            # a separator with nothing after it adds no roll, as in OpenAero (F6)
            pieces = _roll_pieces(roll) if roll else []
            last_direction = last_direction if direction == ";" else -last_direction
            for num, roll_chars in pieces:
                new_rolls = olan_rolls[num] if num else [1]
                rolls = rolls + [
                    replace(create_roll(roll_chars, r * last_direction), piece=piece)
                    for r in new_rolls
                ]
                piece += 1
        return OlanRoll(data, rolls)
