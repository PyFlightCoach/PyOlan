"""F3A families, lettered groups L and M (turnaround humpty bumps).

Conventions decided per family (checked against the USG drawings):

- shape: the humpty bump of a turnaround is entry, a 1/4 loop up, a vertical upline,
  a 1/2 loop that carries on forwards over the top, a vertical downline and a 1/4
  loop out *backwards* (the exit heads the opposite way to the entry). In the loops'
  sense that is 1/4, then 1/2 and 1/4 the other way. Group L starts at the bottom;
  group M ("from top") is its mirror image about the entry height (down first). The two
  vertical lines are equal (one shared ``line_length``), so the figure finishes at the
  height it started.
- the rolls are "<roll> up" and "<roll> down", centred on the vertical lines (as for
  group 18). The up line is the one flown upwards: the first from the bottom, the
  second from the top. L names both; M.1 and M.2 only roll the down line.
- ``(pull, pull, push)``: the stated pull or push of each loop is passed to the loop
  clause (steps.Loop.pull), so the figure is only built if the stated rolls make
  the loops as stated, and the loop and roll directions follow from that. A loop
  between two quarter-rolled lines is in knife-edge flight and is neither pulled nor
  pushed, so it is not checked (the roll directions follow from the first and last loop
  and the knife-edge loop and the rolls are one mirror option, as for the stall turn).
  Where the text gives alternatives for one loop ("pull, pull, push, or pull, push,
  push") that loop is left to the pilot.
- ``with roll options, (half roll up or 1/4 roll up and down)`` (L.11, L.12): an
  Option with one figure for each choice; the roll on the up line only, or the same
  roll on both lines.
"""

from __future__ import annotations

import re
from fractions import Fraction

import schemas.positioning as p

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import is_quarter, require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll

from .families import Modifiers, family  # isort: skip

_PULLS_RE = re.compile(r"^(?:pull|push)(?:, (?:or )?(?:pull|push))*$")
_UP_DOWN_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")
_BOTH_RE = re.compile(r"^(?P<roll>.+?) up and down$")
_BRACKET_RE = re.compile(r"\(([^()]*)\)")


def _pull_spec(group: str) -> list[bool | None]:
    """``pull, pull, push`` or ``pull, pull, push, or pull, push, push`` -> for each
    loop True (pulled), False (pushed) or None (the alternatives differ)."""
    alternatives = [part.strip(" ,") for part in re.split(r",? or (?=pull|push)", group)]
    triples = []
    for alternative in alternatives:
        words = [w.strip() for w in alternative.split(",")]
        if len(words) != 3 or any(w not in ("pull", "push") for w in words):
            raise F3AParseError(f"humpty bump: expected three pulls or pushes, got {group!r}")
        triples.append([w == "pull" for w in words])
    first = triples[0]
    return [first[i] if all(t[i] == first[i] for t in triples) else None for i in range(3)]


def _humpty(
    name: str,
    mods: Modifiers,
    up: OlanRoll | None,
    down: OlanRoll | None,
    pulls: list[bool | None],
) -> list[Clause]:
    sense = -1 if mods.start == "top" else 1
    # path angle after the first loop and after the half loop (the two vertical lines)
    first_line = Fraction(1, 4) * sense % 1
    second_line = Fraction(-1, 4) * sense % 1
    rolls = {"up": up, "down": down}
    first, second = ("down", "up") if mods.start == "top" else ("up", "down")
    # the half loop is flown in knife-edge when the first line has a quarter roll
    knife_edge_loop = is_quarter(rolls[first])
    clauses: list[Clause] = [
        Entry(mods.entry),
        Loop(Fraction(1, 4), sense=sense, pull=pulls[0]),
        Line(frozenset({first_line}), label="first line"),
    ]
    if rolls[first] is not None:
        clauses.append(Roll(rolls[first]))
    clauses.append(
        Loop(
            Fraction(1, 2),
            sense=-sense,
            pull=None if knife_edge_loop else pulls[1],
            knife_edge=True if knife_edge_loop else None,
        )
    )
    clauses.append(Line(frozenset({second_line}), label="second line"))
    if rolls[second] is not None:
        clauses.append(Roll(rolls[second]))
    clauses += [Loop(Fraction(1, 4), sense=-sense, pull=pulls[2]), Exit(mods.exit)]
    return clauses


@family("humpty bump with roll options")
def humpty_bump_options(name: str, mods: Modifiers, phrases: list[str]) -> list[list[Clause]]:
    text = ", ".join(phrases)
    if mods.start is not None or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: no start height expected")
    if not (match := re.fullmatch(r"\((?P<options>[^()]+)\)", text)):
        raise F3AParseError(f"{name}: expected '(<roll> up or <roll> up and down)', got {text!r}")
    choices = match.group("options").split(" or ")
    if len(choices) != 2:
        raise F3AParseError(f"{name}: expected two roll options, got {text!r}")
    figures: list[list[Clause]] = []
    for choice in choices:
        if both := _BOTH_RE.match(choice):
            roll = require_roll(both.group("roll"))
            rolls = (roll, roll)
        elif (up := _UP_DOWN_RE.match(choice)) and up.group("dir") == "up":
            rolls = (require_roll(up.group("roll")), None)
        else:
            raise F3AParseError(f"{name}: unexpected roll option {choice!r}")
        figures.append(_humpty(name, mods, rolls[0], rolls[1], [None, None, None]))
    return figures


def turnaround_humpty_bump(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    """Groups L and M: ``Humpty bump (pull, pull, push) half roll up, 2/4pt roll down``,
    ``Humpty bump from top, half roll down (push, push, push)``."""
    text = ", ".join(phrases)
    pulls: list[bool | None] | None = None
    for group in _BRACKET_RE.findall(text):
        if not _PULLS_RE.match(group) and not re.match(r"^(?:pull|push)", group):
            raise F3AParseError(f"{name}: unexpected {group!r}")
        if pulls is not None:
            raise F3AParseError(f"{name}: the pulls and pushes are given twice")
        pulls = _pull_spec(group)
    if pulls is None:
        raise F3AParseError(f"{name}: the pull or push of each loop is missing")
    text = _BRACKET_RE.sub(" ", text)
    rolls: dict[str, OlanRoll] = {}
    for phrase in (part.strip() for part in text.split(",")):
        if not phrase:
            continue
        if phrase == "inverted exit":  # M.10; "exit inverted" is a shared modifier
            mods.exit = p.Orientation.INVERTED
            continue
        if not (match := _UP_DOWN_RE.match(phrase)) or match.group("dir") in rolls:
            raise F3AParseError(f"{name}: unexpected {phrase!r}, expected a roll up or down")
        rolls[match.group("dir")] = require_roll(match.group("roll"))
    required = {"down"} if mods.start == "top" else {"up", "down"}
    if not required <= set(rolls):
        raise F3AParseError(f"{name}: expected a roll {' and '.join(sorted(required))}, got {phrases!r}")
    return _humpty(name, mods, rolls.get("up"), rolls.get("down"), pulls)
