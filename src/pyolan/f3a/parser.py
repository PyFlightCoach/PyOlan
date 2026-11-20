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
from .families_27_30 import named_step_clauses
from .normalise import Description, normalise, split_description
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
    figure_ndmps,
    mirror_parameters,
    option_name,
    resolve,
)

_ATTITUDE = {"upright": p.Orientation.UPRIGHT, "inverted": p.Orientation.INVERTED}

# shared modifiers, removed from the text wherever they are (order matters)
_MODIFIERS: list[tuple[re.Pattern, str]] = [
    # "from top", "(from bottom)", "from middle (top first)": start height and, from
    # the middle, which half goes first
    (re.compile(r"\(?\bfrom (top|middle|bottom)(?: \((top|bottom) first\))?\)?"), "start"),
    # "(top entry)", "(middle entry, top first)", "middle entry and exit, top first"
    (re.compile(r"\(?\b(top|middle|bottom) entry(?: and exit)?(?:,? (top|bottom) first)?\)?"), "entry"),
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
            case "start" | "entry":
                if mods.start is not None:
                    raise F3AParseError("the start height is given more than once")
                mods.start, mods.first = found[0][0], found[0][1] or None
                mods.entry_form = kind == "entry"
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
    if (named := named_step_clauses(text)) is not None:  # groups 27-30: "<name>. from ..."
        return named
    mods, rest = _shared_modifiers(text)
    mods.forward = desc.group is None or desc.group.isdigit()
    fam, rest = find_family(re.sub(r"\s+", " ", rest).strip(" ,"))
    if not fam.entry_heights and (mods.start == "middle" or mods.first or mods.entry_form):
        raise F3AParseError(f"{fam.name}: a start at {mods.start!r} (first {mods.first!r}) is not supported")
    return fam.build(fam.name, mods, _phrases(rest))


def _display_name(raw: str) -> str:
    text = re.sub(r"^\s*(\d{1,2}|[A-Za-z])\.\d{1,2}\b\s*[-.]?\s*", "", raw)
    text = re.sub(r"\(\s*[kK]\s*\d+\s*\)", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def _position(desc: Description, resolved: Resolved) -> p.Position:
    if desc.group is not None:
        return p.Position.CENTRE if desc.group.isdigit() else p.Position.END
    return p.Position.END if resolved.reverses else p.Position.CENTRE


def _figure(desc: Description, resolved: Resolved) -> a.Figure:
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
            ndmps={option_name(group): [values, [-v for v in values]] for group, values in mirror.items()}
            | figure_ndmps(resolved.items),
        )
    return a.Figure(
        info=info,
        elements=create_elements(resolved.items, linked=False),
        ndmps=figure_ndmps(resolved.items),
    )


# Catalogue entries whose words (the same in the 2026 rulebook and the USG list) contradict
# their drawing and metadata: number -> (catalogued words, corrected words). Applied only
# when the number is known and the words are the catalogued ones, so a later corrected
# catalogue passes through unchanged. Decided 2026-11-19 (best guess, to be reviewed).
ERRATA: dict[str, tuple[str, str]] = {
    # the stated last push exits inverted; the drawing exits upright, as L.8 does with
    # a last pull
    "L.7": (
        "Humpty bump (pull, pull, push, or pull, push, push) 1/4 roll up, 3/4 roll down",
        "Humpty bump (pull, pull, pull, or pull, push, pull) 1/4 roll up, 3/4 roll down",
    ),
    # P.2's words; the drawing starts at the top
    "P.6": (
        "Vertical 5/8 loop from upright, snap-roll, roll, exit inverted",
        "Vertical 5/8 loop from top upright, snap-roll, roll, exit inverted",
    ),
    # the drawing is low, inverted to inverted (P.11's with a 1/4 roll exit)
    "P.12": (
        "Vertical 5/8 loop from top inverted, 3/4 snap-roll, 1/4 half roll, exit upright",
        "Vertical 5/8 loop from inverted, 3/4 snap-roll, 1/4 roll, exit inverted",
    ),
}


def apply_errata(desc: Description) -> Description:
    """The corrected description for a catalogue entry listed in ``ERRATA``."""
    if desc.number in ERRATA:
        catalogued, corrected = ERRATA[desc.number]
        if desc.text == normalise(catalogued):
            return replace(desc, raw=corrected, text=normalise(corrected))
    return desc


_HEIGHT = {"bottom": p.Height.BTM, "middle": p.Height.MID, "top": p.Height.TOP}
_BOTH_RE = re.compile(r"\b(?:top|middle|bottom) entry and exit\b")
_EXIT_HEIGHT_RE = re.compile(r"\bexit (top|middle|bottom)\b")


def stated_heights(
    text: str, number: str | None = None
) -> tuple[set[p.Height] | None, set[p.Height] | None]:
    """The entry and exit heights a catalogue description states in words.

    Returns ``(entry, exit)``; each is a non-empty set, or None where the words leave
    the height open (including figures whose family would default to the bottom).
    Stated words are hard restrictions: "from top", "from middle (top first)",
    "(middle entry, top first)" and "from top upright" state the entry; "middle entry
    and exit" and "exit middle inverted" state the exit. Nothing else is inferred.
    """
    desc = apply_errata(split_description(text, number))
    mods, _ = _shared_modifiers(desc.text)
    entry = {_HEIGHT[mods.start]} if mods.start is not None else None
    if match := _EXIT_HEIGHT_RE.search(desc.text):
        exit_ = {_HEIGHT[match.group(1)]}
    elif _BOTH_RE.search(desc.text):
        exit_ = set(entry)
    else:
        exit_ = None
    return entry, exit_


def parse_f3a_description(
    text: str, number: str | None = None, k: int | None = None
) -> a.Figure | a.Option:
    """Parse a catalogue line such as ``01.9 Knife-edge loop from top (K6)``.

    The number and K may be passed separately; if the text has them too they
    must agree. Entries listed in ``ERRATA`` are parsed from their corrected words.

    Roll and yaw directions are the pilot's choice. Roll directions are left
    to the builder's reversible rolls, or linked in a mirror roll_option where
    they set the knife-edge side. A loop whose direction the words leave open
    gives an Option with one figure for each direction; the first keeps the
    travel direction (forwards for centre figures, backwards for turnarounds),
    as the drawings show.
    """
    desc = apply_errata(split_description(text, number))
    if k is not None:
        if desc.k is not None and desc.k != k:
            raise F3AParseError(f"K {k} does not match the text's K {desc.k}")
        desc = replace(desc, k=k)
    clauses = description_clauses(desc)
    # a family may return several clause lists, one for each choice the pilot is given
    alternatives = clauses if clauses and isinstance(clauses[0], list) else [clauses]
    forward = desc.group is None or desc.group.isdigit()
    figures = [
        _figure(desc, resolved)
        for choice in alternatives
        for resolved in resolve(choice, forward=forward)
    ]
    return figures[0] if len(figures) == 1 else a.Option(figures=figures)
