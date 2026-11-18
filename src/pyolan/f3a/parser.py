"""parse_f3a_description: an F3A catalogue description -> schemas.aresti.Figure.

Two styles are read:

1. family plus modifiers, ``Square loop on corner from top with half rolls in
   legs 1 & 3, inverted entry (K4)`` (see families.py);
2. step by step, ``Figure N. Vertical upline from upright, 1/4 roll, stall
   turn, 1/8 knife-edge loop, ...`` where each clause is one step.

Both produce clauses (steps.py) that are flown to resolve the loop and roll
directions, then turned into elements.
"""

from __future__ import annotations

import re
from dataclasses import replace
from fractions import Fraction

import schemas.positioning as p
from schemas import aresti as a
from schemas.maninfo import ManInfo

from .errors import F3AParseError
from .families import Modifiers, find_family
from .normalise import Description, split_description
from .rolls import parse_roll
from .steps import (
    DOWN_LINE,
    UP,
    VERTICAL,
    Clause,
    Entry,
    Exit,
    Line,
    Loop,
    Resolved,
    Roll,
    StallTurn,
    create_elements,
    mirror_parameters,
    resolve,
)

_ATTITUDE = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}

# shared modifiers, removed from the text wherever they are (order matters)
_MODIFIERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\(?\bfrom (top|bottom)\)?"), "start"),
    (re.compile(r"\binverted entry and exit\b"), "inverted both"),
    (re.compile(r"\binverted entry\b"), "inverted entry"),
    (re.compile(r"\bexit inverted\b"), "inverted exit"),
]


def _shared_modifiers(text: str) -> tuple[Modifiers, str]:
    mods = Modifiers()
    for pattern, kind in _MODIFIERS:
        found = pattern.findall(text)
        if len(found) > 1:
            raise F3AParseError(f"{kind!r} is given more than once")
        if not found:
            continue
        text = pattern.sub(" ", text)
        match kind:
            case "start":
                mods.start = found[0]
            case "inverted both":
                mods.entry = mods.exit = p.Orientation.INVERTED
            case "inverted entry":
                mods.entry = p.Orientation.INVERTED
            case "inverted exit":
                mods.exit = p.Orientation.INVERTED
    return mods, text


def _phrases(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip(" ,")
    text = re.sub(r"^with\b", "", text).strip(" ,")
    parts = re.split(r",|\bwith\b", text)
    return [part.strip() for part in parts if part.strip()]


# ---------------------------------------------------------------- step style

_STEP_NAME_RE = re.compile(r"^(?P<name>[a-z0-9 ]+?)\. (?P<rest>.*)$")
_ENTRY_RE = re.compile(r"^vertical (?:up)?line from (?P<att>upright|inverted)$")
_LINE_RE = re.compile(
    r"^(?P<angle>45 degree|vertical) (?P<ke>knife-edge )?(?P<dir>upline|downline|line)$"
)
_LOOP_RE = re.compile(
    r"^(?P<amount>\d/\d) (?P<ke>knife-edge )?(?P<pp>pushed |pulled )?loop$"
)
_EXIT_RE = re.compile(r"^exit (?P<att>upright|inverted)$")

_45_UP = frozenset({Fraction(1, 8), Fraction(3, 8)})
_45_DOWN = frozenset({Fraction(5, 8), Fraction(7, 8)})


def _line_angles(angle: str, direction: str) -> frozenset[Fraction]:
    if angle == "vertical":
        return {"upline": UP, "downline": DOWN_LINE, "line": VERTICAL}[direction]
    return {"upline": _45_UP, "downline": _45_DOWN, "line": _45_UP | _45_DOWN}[direction]


def _is_step_style(text: str) -> bool:
    match = _STEP_NAME_RE.match(text)
    body = match.group("rest") if match else text
    return bool(_ENTRY_RE.match(body.split(", ")[0]))


def step_clauses(text: str) -> tuple[str | None, list[Clause]]:
    name = None
    if match := _STEP_NAME_RE.match(text):
        name, text = match.group("name"), match.group("rest")
    clauses: list[Clause] = []
    for phrase in (part.strip() for part in text.split(",")):
        if match := _ENTRY_RE.match(phrase):
            if clauses:
                raise F3AParseError(f"entry {phrase!r} is not first")
            clauses += [Entry(_ATTITUDE[match.group("att")]), Line(UP)]
        elif match := _LINE_RE.match(phrase):
            clauses.append(
                Line(
                    _line_angles(match.group("angle"), match.group("dir")),
                    knife_edge=True if match.group("ke") else None,
                )
            )
        elif match := _LOOP_RE.match(phrase):
            pp = (match.group("pp") or "").strip()
            clauses.append(
                Loop(
                    Fraction(match.group("amount")),
                    pull={"pulled": True, "pushed": False}.get(pp),
                    knife_edge=True if match.group("ke") else None,
                )
            )
        elif phrase == "stall turn":
            clauses.append(StallTurn())
        elif match := _EXIT_RE.match(phrase):
            clauses.append(Exit(_ATTITUDE[match.group("att")]))
        elif (roll := parse_roll(phrase)) is not None:
            clauses.append(Roll(roll))
        else:
            raise F3AParseError(f"unknown step {phrase!r}")
    return name, clauses


# ---------------------------------------------------------------- entry point


def description_clauses(desc: Description) -> list[Clause]:
    text = desc.text
    if _is_step_style(text):
        return step_clauses(text)[1]
    mods, rest = _shared_modifiers(text)
    fam, rest = find_family(re.sub(r"\s+", " ", rest).strip(" ,"))
    return fam.build(fam.name, mods, _phrases(rest))


def _display_name(raw: str) -> str:
    text = re.sub(r"^\s*(\d{1,2}|[A-Za-z])\.\d{1,2}\b\s*[-.]?\s*", "", raw)
    text = re.sub(r"\(\s*[kK]\s*\d+\s*\)", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def _position(desc: Description, resolved: Resolved) -> p.Position:
    if desc.group is not None:
        return p.Position.CENTRE if desc.group.isdigit() else p.Position.END
    return p.Position.END if resolved.reverses else p.Position.CENTRE


def parse_f3a_description(
    text: str, number: str | None = None, k: int | None = None
) -> a.Figure:
    """Parse a catalogue line such as ``01.9 Knife-edge loop from top (K6)``.

    The number and K may be passed separately; if the text has them too they
    must agree. Turnaround figures (lettered groups)
    reverse the direction of flight, so where a loop's sense is open it is
    chosen to travel back rather than forward.
    """
    desc = split_description(text, number)
    if k is not None:
        if desc.k is not None and desc.k != k:
            raise F3AParseError(f"K {k} does not match the text's K {desc.k}")
        desc = replace(desc, k=k)
    clauses = description_clauses(desc)
    forward = desc.group is None or desc.group.isdigit()
    resolved = resolve(clauses, forward=forward)

    info = ManInfo.build(
        _display_name(desc.raw),
        desc.number or "f3a",
        desc.k if desc.k is not None else 0,
        _position(desc, resolved),
        p.BoxLocation(height=resolved.entry_height, orientation=resolved.entry),
        p.BoxLocation(height=resolved.exit_height, orientation=resolved.exit),
    )
    mirror = mirror_parameters(resolved.items)
    if mirror:
        return a.Figure(
            info=info,
            elements=create_elements(resolved.items, linked=True),
            ndmps={"roll_option": [mirror, [-v for v in mirror]]},
        )
    return a.Figure(info=info, elements=create_elements(resolved.items, linked=False), ndmps={})
