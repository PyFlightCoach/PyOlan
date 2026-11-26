"""A comparable form of an OLAN sequence: what is flown, without how it is drawn.

Two OLAN strings of the same sequence differ in their drawing: figure positions
("(13,8)", "3>"), scale ("2%"), line lengths ("~", "'", "`", "."), "+" markers,
comments, entry markers ("eu", "ej") and spacing. ``sequence_key`` keeps only the
figures, each written the same way, so that two strings fly the same figures in the
same order exactly when their keys are equal. It does not build any figure (no
builder is needed) and takes well under a millisecond for a sequence.
"""

from __future__ import annotations

import re

from schemas import positioning as p

from .drawing import olan_items, strip_comments
from .errors import NoFigureLeft, OlanParseError
from .figure_parser import OlanFig

_ATTITUDE = re.compile(r"^[-+]+|[-+]+$")


def figure_key(fig: OlanFig) -> str:
    """One figure as it is flown: its OLAN without drawing characters or comments,
    with a single entry and exit attitude marker ("+" upright, "-" inverted)."""
    body = _ATTITUDE.sub("", strip_comments(fig.rawfig))
    entry = "-" if fig.entry == p.Orientation.INVERTED else "+"
    exit = "-" if fig.exit == p.Orientation.INVERTED else "+"
    return f"{entry}{body}{exit}"


def figure_keys(olan: str) -> list[str]:
    """The key of each figure of an OLAN sequence, in order. Raises OlanParseError
    for an item that is neither a figure nor a drawing command."""
    items = olan_items(olan)
    total = len(items)
    keys: list[str] = []
    while items:
        offset = total - len(items)
        try:
            fig, items = OlanFig.take(items)
        except NoFigureLeft:
            break
        except OlanParseError as ex:
            # placed in the whole sequence, as parse_olan reports it
            raise ex.at(index=offset + ex.index, figure=len(keys) + 1) from None
        keys.append(figure_key(fig))
    return keys


def sequence_key(olan: str) -> str:
    """The figures of an OLAN sequence as one string, equal for two OLAN strings
    exactly when they fly the same figures in the same order. Raises OlanParseError
    for OLAN that cannot be read."""
    return " ".join(figure_keys(olan))
