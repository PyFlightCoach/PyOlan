"""Which F3A catalogue entries the user has reviewed.

The parser reads every entry of the 2026 rulebook (681), but only some of the figures
it builds have been checked against the drawings by the user (the review batches in
docs/plans/f3a-unknown-import.md). Numbers are the rulebook's (``01.9``, ``K.1``);
the rulebook's Q.8 and Q.9 are the USG list's Q.7 and Q.8.

Reviewed (decided 2026-11-19): groups 01-22 and 26 (batches 1-5) and the slow roll
entries 23.15 and 23.16. The catalogue review of 2026-11-21 (batch 6: groups 23, 24, 25,
27-30 and A-Q, with the ERRATA entries P.6 and P.12) gave every group a verdict; the
changes it asked for (14.22, L.7, P, 21, 25, 28, 30, C, D) are in the parser. Group J
was reviewed on 2026-11-22, after its cross-box top hats became a depth-correction Option
with free turnaround lines (docs/plans/f3a-catalogue-continuation.md, phase J). Every
group is now reviewed. Add numbers or groups here when a review is accepted.
"""

from __future__ import annotations

from .normalise import normalise_number

REVIEWED_GROUPS: frozenset[str] = frozenset(
    [f"{n:02d}" for n in range(1, 31)] + ["A", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "P", "Q"]
)
"""Groups of which every entry is reviewed."""

REVIEWED_NUMBERS: frozenset[str] = frozenset({"23.15", "23.16"})
"""Reviewed entries of groups that are not reviewed as a whole."""


def is_reviewed(number: str) -> bool:
    """Whether the catalogue entry (``01.9``, ``1.9``, ``k.1``) has been reviewed."""
    number = normalise_number(number)
    return number.split(".")[0] in REVIEWED_GROUPS or number in REVIEWED_NUMBERS
