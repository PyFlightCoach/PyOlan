"""Normalise F3A catalogue descriptions.

The catalogue text comes from the FAI sporting code (Annex 5G), the USG drawings
and ListOfManeuvers.txt and the F3A Unknown Generator. They differ in typography
(``½`` / ``1/2``, ``knife edge`` / ``knife-edge``, ``45°`` / ``45 degree``) and
the rulebook PDF adds artefacts such as ``11/4`` for ``1¼``. normalise() maps
these onto one lower case form that the grammars read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import F3AParseError

_FRACTIONS = {
    "½": "1/2",
    "¼": "1/4",
    "¾": "3/4",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

_K_RE = re.compile(r"\(\s*k\s*(\d+)\s*\)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^\s*(\d{1,2}|[A-Za-z])\.(\d{1,2})\b\s*[-.]?\s*")

# (pattern, replacement), applied in order to the lower case text
_SUBSTITUTIONS: list[tuple[str, str]] = [
    (r"[‐-―]", "-"),  # unicode dashes
    (r"[’‘`]", "'"),
    (r"\b1(1/[248])\b", r"1 \1"),  # PDF artefact: 11/4 for 1¼
    (r"(\d)\s*(?:°|degrees?\b|deg\b)", r"\1 degree"),
    (r"\bknife[\s-]*edge\b", "knife-edge"),
    (r"\bup[\s-]+line\b", "upline"),
    (r"\bdown[\s-]+line\b", "downline"),
    (r"\bsnap[\s-]+roll", "snap roll"),
    (r"\bstall[\s-]*turn\b", "stall turn"),
    (r"\b(\d+(?:/\d+)?\s*-?\s*pt\.)(?=[a-z])", r"\1 "),  # "3/4 pt.roll" (24.1)
    (r"\b(\d+(?:/\d+)?)\s*-?\s*(?:pt\.?|points?)(?=\s|$|,)", r"\1-point"),
    (r"\bcenter\b", "centre"),
    (r"\s*&\s*", " & "),
    (r"\s*,\s*", ", "),
    (r"\(\s+", "("),
    (r"\s+\)", ")"),
    (r"\s+", " "),
]


def normalise(text: str) -> str:
    """Lower case, unify typography and spelling, collapse whitespace."""
    for symbol, fraction in _FRACTIONS.items():
        # 1¼ -> 1 1/4, ¼ -> 1/4
        text = re.sub(rf"(\d){symbol}", rf"\1 {fraction}", text)
        text = text.replace(symbol, fraction)
    text = text.lower()
    for pattern, replacement in _SUBSTITUTIONS:
        text = re.sub(pattern, replacement, text)
    return text.strip(" ,.")


def normalise_number(number: str) -> str:
    """``1.9`` -> ``01.9``, ``a.5`` -> ``A.5``."""
    match = re.fullmatch(r"\s*(\d{1,2}|[A-Za-z])\.(\d{1,2})\s*", number)
    if not match:
        raise F3AParseError(f"not a catalogue number: {number!r}")
    group, item = match.groups()
    group = f"{int(group):02d}" if group.isdigit() else group.upper()
    return f"{group}.{int(item)}"


@dataclass(frozen=True)
class Description:
    """A catalogue line split into its parts."""

    raw: str
    text: str  # normalised description, without number or K
    number: str | None = None
    k: int | None = None

    @property
    def group(self) -> str | None:
        return self.number.split(".")[0] if self.number else None


def split_description(raw: str, number: str | None = None) -> Description:
    """Separate the catalogue number and K factor from the description.

    ``01.9 Knife-edge loop from top (K6)`` gives number ``01.9``, K 6 and text
    ``knife-edge loop from top``. A number passed in must agree with one in the
    text. Repeated K markers (a PDF artefact) must agree with each other.
    """
    text = raw.strip()
    match = _NUMBER_RE.match(text)
    if match:
        found = normalise_number(f"{match.group(1)}.{match.group(2)}")
        if number is not None and normalise_number(number) != found:
            raise F3AParseError(f"number {number!r} does not match the text {found!r}")
        number = found
        text = text[match.end():]
    elif number is not None:
        number = normalise_number(number)

    ks = {int(k) for k in _K_RE.findall(text)}
    if len(ks) > 1:
        raise F3AParseError(f"conflicting K factors {sorted(ks)} in {raw!r}")
    text = _K_RE.sub(" ", text)
    return Description(raw=raw, text=normalise(text), number=number, k=ks.pop() if ks else None)
