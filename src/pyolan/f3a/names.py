"""Names for F3A catalogue figures.

A catalogue description runs to 150 characters, but ``ManInfo.name`` and ``short_name`` are
stored in 30 characters. The name is the figure's family in title case, followed by a compact
summary of its rolls when that fits: ``Rolling Circle, 4 rolls outside``. The entry and exit
attitude and height are left out, because ``ManInfo`` holds them. The short name is one word that
works as an attribute (``tHat``, ``sqV8``), in the style of the known F3A schedules. The full
description stays in the catalogue, and a schedule keeps the catalogue number of each figure it
copies, so nothing is lost by the shorter names.

Short names are not unique: a schedule makes them unique when it adds a figure.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from .normalise import Description

MAX_LENGTH = 30


class FamilyName(NamedTuple):
    groups: frozenset[str] | None  # catalogue groups this entry applies to, None for any
    prefix: str  # a regular expression for the normalised words that start the description
    name: str  # title case name; empty: the whole description, compacted, is the name
    short_name: str
    alias: str = ""  # a shorter name, used before a roll summary (for the whole family, so it reads the same)


def _f(prefix: str, name: str, short_name: str, alias: str = "", groups: str | None = None) -> FamilyName:
    return FamilyName(frozenset(groups.split()) if groups else None, prefix, name, short_name, alias)


# The longest matching prefix wins, so "square loop on corner" is found before "square loop".
FAMILIES: list[FamilyName] = [
    _f("loop", "Loop", "loop"),
    _f("rolling loop", "Rolling Loop", "rLoop"),
    _f("knife-edge loop", "Knife-Edge Loop", "keLoop"),
    _f("two loops", "Two Loops", "loops"),
    _f("avalanche", "Avalanche", "aval"),
    _f("triangular loop", "Triangle", "trgle"),
    _f("knife-edge triangular loop", "Knife-Edge Triangle", "keTrgl", "KE Triangle"),
    _f("square loop", "Square Loop", "sqL"),
    _f("square loop on corner", "Square Loop on Corner", "sqLC"),
    _f("six sided loop", "Six Sided Loop", "hexL"),
    _f("cobra roll", "Cobra Roll", "cobra"),
    _f("golf ball", "Golf Ball", "golf"),
    _f("cuban eight", "Cuban Eight", "cuban"),
    _f("reverse cuban eight", "Reverse Cuban Eight", "rCuban", "Rev Cuban Eight"),
    _f("knife-edge cuban eight", "Knife-Edge Cuban Eight", "keCuban"),
    _f("knife-edge reverse cuban eight", "Knife-Edge Rev Cuban Eight", "keRCuban", "KE Rev Cuban Eight"),
    _f("45 degree down", "45 Downline", "dn45", groups="11"),
    _f("45 degree up", "45 Upline", "up45", groups="11"),
    _f("figure z", "Figure Z", "figZ"),
    _f("hourglass", "Hourglass", "hrglss"),
    _f("vertical eight", "Vertical Eight", "v8"),
    _f("vertical knife-edge eight", "Vertical Knife-Edge Eight", "keV8", "KE Vertical Eight"),
    _f("square horizontal eight", "Square Horizontal Eight", "sqH8", "Sq Horizontal Eight"),
    _f("square vertical eight", "Square Vertical Eight", "sqV8", "Sq Vertical Eight"),
    _f("figure m", "Figure M", "figM"),
    _f("top hat", "Top Hat", "tHat"),
    _f("humpty bump", "Humpty Bump", "humpty", "Humpty"),
    _f("", "", "spin", groups="19 G"),  # "2 1/2 turn spin": the words are the name
    _f("stall turn", "Stall Turn", "stall"),
    _f("double immelmann", "Double Immelmann", "dImm"),
    _f("rolling circle", "Rolling Circle", "rCirc"),
    _f("", "", "rollC", groups="23"),  # roll combinations: the words are the name
    _f("knife-edge flight", "Knife-Edge Flight", "keFlt", groups="23"),
    _f("reverse knife-edge flight", "Reverse Knife-Edge Flight", "rKeFlt", groups="23"),
    _f("one horizontal snap roll", "Snap Roll", "snap", groups="23"),
    _f("double key", "Double Key", "dKey"),
    _f("horizontal eight", "Horizontal Eight", "h8"),
    _f("figure n", "Figure N", "figN"),
    _f("infinite loop", "Infinite Loop", "infL"),
    _f("figure h", "Figure H", "figH"),
    _f("half clover leaf", "Half Clover Leaf", "hClvr"),
    _f("diamond in a loop", "Diamond in a Loop", "diamL"),
    _f("half square loop", "Half Square Loop", "hSqL"),
    _f("half square loop on corner", "Half Square Loop on Corner", "hSqLC"),
    _f(r"half square loop on corner from \w+ up", "Half Sq Loop on Corner, Up", "hSqLC", groups="N"),
    _f(r"half square loop on corner from \w+ down", "Half Sq Loop on Corner, Down", "hSqLC", groups="N"),
    _f("split s", "Split S", "splitS"),
    _f("immelmann turn", "Immelmann", "imm"),
    _f("figure 6", "Figure 6", "fig6"),
    _f("figure 9", "Figure 9", "fig9"),
    _f("half cuban eight", "Half Cuban Eight", "hCuban"),
    _f("half reverse cuban eight", "Half Reverse Cuban Eight", "hRCuban", "Half Rev Cuban"),
    _f("45 degree up", "45 Half Loop", "hLoop45", groups="K"),
    _f("45 degree upline", "Knife-Edge 45 Half Loop", "keHL45", groups="K"),
    _f("vertical 5/8 loop", "5/8 Loop", "loop58"),
    _f("almost 8", "Almost Eight", "alm8"),
]

# Words that ManInfo already holds (entry and exit attitude and height), or that are a check on
# the shape rather than its content. Removed from the roll summary.
_DROP = [
    r"\(?from (?:the )?(?:top|bottom|middle)(?: \((?:top|bottom) first\))?(?: (?:upright|inverted))?\)?",
    r"\(?(?:top|bottom|middle) (?:entry|exit)(?: and exit)?(?:, (?:top|bottom) first)?\)?",
    r"inverted entry and exit",
    r"inverted entry",
    r"(?:inverted|upright) (?:entry|exit)",
    r"exit (?:middle |top |bottom )?(?:inverted|upright)",
    r"entry (?:upright|inverted)",
    r"from (?:upright|inverted)",
    r"centre half-loop is always flown negative \(inverted\)",
    r"\([^()]*degrees[^()]*\)",  # 09.1: the golf ball's shape spelt out
    r"\((?:(?:pull|push)(?:, (?:or )?)?)+\)",  # loop directions: (pull, pull, push)
    r"\(base at top\)",  # every knife-edge triangle
    r"\(\s*\)",
]

# Roll phrases in fewer characters: "half roll up" -> "1/2 up", "2/4-point rolls" -> "2/4pt rolls".
_COMPACT = [
    (r"(\d)-point\b", r"\1pt"),
    (r"\bhalf\b", "1/2"),
    (r"\bone (?=roll|snap)", "1 "),
    (r"\btwo (?=\d)", "2x "),
    (r"\bfour (?=\d)", "4x "),
    (r"\b(?:(\d)|three|four) consecutive\b", lambda m: (m.group(1) or {"t": "3", "f": "4"}[m.group(0)[0]]) + "x"),
    (r"\b(\dx [\d/]+pt) rolls reversed\b", r"\1 reversed"),
    (r"\bin 45 degree legs\b", "in 45s"),
    (r"\bhorizontal leg\b", "base"),
    (r"\((?:inside or outside|up or down)\)", ""),  # K: the pilot's choice
    (r"\(([^()]*)\)", r"\1"),
    (r"\b(in|out)side\b", r"\1"),
    (r"\b(up|down) and (up|down)\b", r"\1 & \2"),
    (r"\b(\S+(?: \S+)?) first (top|bottom), (\S+(?: \S+)?) second\b", r"\1 then \3 at \2"),
    (r"\b(\S+(?: \S+)?) first, (\S+(?: \S+)?) second\b", r"\1 then \2"),
    (r"\bfull (roll|snap)", r"\1"),
    (r"\bsnap roll", "snap"),
    (r"\b(\d[\d/ ]*(?:pt)?) (?:rolls?|snap rolls?) (up|down)\b", r"\1 \2"),
    (r"\bintegrated\b", "int"),
]

# For names made from the whole description (spins, roll combinations): only typography.
_COMPACT_WORDS = [
    (r"\b(four|eight) point\b", lambda m: {"four": "4", "eight": "8"}[m.group(1)] + "pt"),
    (r"(\d)-point\b", r"\1pt"),
    (r"\bsnap roll", "snap"),
    (r"\b(two|three)(?= turn)", lambda m: {"two": "2", "three": "3"}[m.group(1)]),
    (r"\bfull snap\b", "snap"),
]

_SMALL = {"a", "and", "at", "in", "of", "on", "with"}


def title(text: str) -> str:
    """Title case, leaving numbers, fractions and short joining words alone."""
    return " ".join(w if w in _SMALL or not w[0].isalpha() else w[0].upper() + w[1:] for w in text.split())


def family_name(desc: Description) -> FamilyName | None:
    """The table entry whose prefix starts the description (longest first)."""
    found = None
    for fam in FAMILIES:
        if fam.groups is not None and desc.group not in fam.groups:
            continue
        if re.match(fam.prefix, desc.text) and (found is None or len(fam.prefix) > len(found.prefix)):
            found = fam
    return found


def _clean(text: str, rules) -> str:
    for pattern in _DROP:
        text = re.sub(pattern, " ", text)
    for pattern, replacement in rules:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"^\W*with\b", "", text.strip(" ,.:"))
    text = re.sub(r"\s+", " ", re.sub(r"\s*[,.](?:\s+|$)[\s,.]*", ", ", text))
    return text.strip(" ,.:")


def _fit(text: str) -> str:
    """``text`` if it fits, else its leading comma-separated clauses that fit, else a hard cut."""
    if len(text) <= MAX_LENGTH:
        return text
    clauses = text.split(", ")
    for n in range(len(clauses) - 1, 0, -1):
        if len(head := ", ".join(clauses[:n])) <= MAX_LENGTH:
            return head
    return text[:MAX_LENGTH].rsplit(" ", 1)[0]


def catalogue_names(desc: Description) -> tuple[str, str]:
    """``(name, short_name)`` for a catalogue description (after errata)."""
    fam = family_name(desc)
    if fam is None:
        return _fit(title(_clean(desc.text, _COMPACT_WORDS))), "f3a"
    if not fam.name:
        words = title(_clean(desc.text, _COMPACT_WORDS))
        return _fit(words if len(words) <= MAX_LENGTH else words.replace("pt Roll", "pt")), fam.short_name
    rolls = _clean(desc.text[re.match(fam.prefix, desc.text).end():], _COMPACT)
    if not rolls:
        return fam.name, fam.short_name
    name = fam.alias or fam.name
    candidates = [f"{name}, {rolls}", f"{name}, {rolls.replace(',', '')}"]
    return next((c for c in candidates if len(c) <= MAX_LENGTH), fam.name), fam.short_name
