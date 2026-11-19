"""Which F3A catalogue entries the user has reviewed.

The parser reads every entry of the 2026 rulebook (681), but only some of the figures
it builds have been checked against the drawings by the user (the review batches in
docs/plans/f3a-unknown-import.md). Numbers are the rulebook's (``01.9``, ``K.1``);
the rulebook's Q.8 and Q.9 are the USG list's Q.7 and Q.8.

Reviewed (decided 2026-11-19): groups 01-22 and 26 (batches 1-5) and the slow roll
entries 23.15 and 23.16. The rest of group 23 and the batch 6 groups (23, 24, 25,
27-30, A-Q), including the ``ERRATA`` entries (L.7, P.6, P.12), are unreviewed until the
batch 6 review. Add numbers or groups here when a review is accepted.
"""

from __future__ import annotations

from .normalise import normalise_number

REVIEWED_GROUPS: frozenset[str] = frozenset(
    [f"{n:02d}" for n in range(1, 23)] + ["26"]
)
"""Groups of which every entry is reviewed."""

REVIEWED_NUMBERS: frozenset[str] = frozenset({"23.15", "23.16"})
"""Reviewed entries of groups that are not reviewed as a whole."""


def is_reviewed(number: str) -> bool:
    """Whether the catalogue entry (``01.9``, ``1.9``, ``k.1``) has been reviewed."""
    number = normalise_number(number)
    return number.split(".")[0] in REVIEWED_GROUPS or number in REVIEWED_NUMBERS
