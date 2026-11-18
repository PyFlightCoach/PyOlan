"""Roll phrases in F3A descriptions -> pyolan.rolls.OlanRoll.

Examples (normalised text): ``half roll``, ``full roll``, ``one roll``,
``2 rolls``, ``1/4 roll``, ``3/4 roll``, ``8-point roll``, ``2/4-point roll``,
``snap roll``, ``full snap``, ``1 1/2 snap``, ``1 negative snap``,
``1 positive snap`` (the default),
``1 1/4 snap roll``, ``three consecutive 1/4 rolls``.

Directions are not part of the phrase: every roll is returned positive and the
figure builder chooses the signs.
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll, ORoll, ro, sn
from .errors import F3AParseError

_WORDS = {
    "a": Fraction(1),
    "one": Fraction(1),
    "full": Fraction(1),
    "single": Fraction(1),
    "two": Fraction(2),
    "three": Fraction(3),
    "four": Fraction(4),
    "half": Fraction(1, 2),
    "quarter": Fraction(1, 4),
}

AMOUNT = r"(?:\d+ \d+/\d+|\d+/\d+|\d+|a|one|full|single|two|three|four|half|quarter)"


def parse_amount(text: str) -> Fraction:
    """``1 1/2`` -> 3/2, ``half`` -> 1/2, ``two`` -> 2."""
    text = text.strip()
    if text in _WORDS:
        return _WORDS[text]
    parts = text.split(" ")
    try:
        return sum((Fraction(part) for part in parts), Fraction(0))
    except (ValueError, ZeroDivisionError) as exc:
        raise F3AParseError(f"not an amount: {text!r}") from exc


_POINT_RE = re.compile(rf"^(?:(?P<count>\d+)/)?(?P<points>\d+)-point rolls?$")
_SNAP_RE = re.compile(
    rf"^(?:(?P<amount>{AMOUNT}) )?(?:(?P<sign>negative|positive) )?snap(?: rolls?)?$"
)
_ROLL_RE = re.compile(rf"^(?:(?P<amount>{AMOUNT}) )?rolls?$")
_CONSECUTIVE_RE = re.compile(rf"^(?P<count>{AMOUNT}) consecutive (?P<amount>{AMOUNT}) rolls$")


def _float(value: Fraction) -> float:
    return float(value)


def parse_roll(phrase: str) -> OlanRoll | None:
    """Parse a whole phrase as a roll, or return None if it is not one."""
    phrase = phrase.strip()
    rolls: list[ORoll]
    if match := _POINT_RE.match(phrase):
        points = int(match.group("points"))
        count = int(match.group("count") or points)
        if points not in (2, 4, 8) or count > points:
            raise F3AParseError(f"unsupported point roll: {phrase!r}")
        rolls = [ro(1 / points) for _ in range(count)]
    elif match := _CONSECUTIVE_RE.match(phrase):
        count = parse_amount(match.group("count"))
        if count.denominator != 1:
            raise F3AParseError(f"not a count: {phrase!r}")
        rolls = [ro(_float(parse_amount(match.group("amount")))) for _ in range(int(count))]
    elif match := _SNAP_RE.match(phrase):
        amount = parse_amount(match.group("amount")) if match.group("amount") else Fraction(1)
        rolls = [sn(_float(amount), match.group("sign") == "negative")]
    elif match := _ROLL_RE.match(phrase):
        # "half rolls" is the plural of half roll, used for several slots
        amount = parse_amount(match.group("amount")) if match.group("amount") else Fraction(1)
        rolls = [ro(_float(amount))]
    else:
        return None
    return OlanRoll(phrase, rolls)


def require_roll(phrase: str) -> OlanRoll:
    roll = parse_roll(phrase)
    if roll is None:
        raise F3AParseError(f"not a roll: {phrase!r}")
    return roll


def signed(roll: OlanRoll, sign: int) -> OlanRoll:
    """The same roll flown the other way when sign is -1."""
    if sign == 1:
        return roll
    return OlanRoll(
        roll.rawroll,
        [ORoll(r.kind, -r.turns, r.negative) for r in roll.roll_arr],
    )


def is_quarter(roll: OlanRoll | None) -> bool:
    """True if the roll leaves the wings vertical (its total is an odd quarter)."""
    return roll is not None and abs(roll.total()) % 0.5 == 0.25
