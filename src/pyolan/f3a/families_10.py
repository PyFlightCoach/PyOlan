"""F3A families, group 10: Cuban eights.

Conventions decided per family (check against the drawings at review):

- Cuban eight (from bottom): two loops joined by two crossing 45 degree
  lines, the OpenAero shape. Level entry, 5/8 loop, 45 degree line, 3/4 loop
  the other way, 45 degree line, 1/8 loop to level exit. The first loop turns
  towards the entry's top (up), the second the other way. "from top" is the
  mirror image about the entry height.
- reverse Cuban eight: the same figure flown in the other order: 1/8 loop up,
  45 degree line, 3/4 loop, 45 degree line, 5/8 loop to level. The drawings
  show the loops outside the crossing on the side of the entry line, as the
  forward figure's reverse.
- closure: the figure finishes at its entry height (decided 2026-11-18). With
  equal 45 degree lines this needs each to be 2 loop radii, set as the builder
  expression "(2*loop_radius)". A roll and its pads that are longer than that
  lengthen the line, so the layout has to raise the radius.
- rolls: "<rolls>" with no place gives one roll of that kind on each of the two
  45 degree lines, centred on the line (decided 2026-11-18, although the drawings
  put the arrow in the half before the crossing).
  Whether the loops are pulled or pushed follows from the rolls (a half roll
  or 2/4-point roll on each line gives two inside loops, a full roll on each
  line makes the second loop an outside loop, as the drawing shows it dashed).
  A lone roll phrase must be plural ("full rolls"): there are two lines.
- knife-edge Cuban eight: the same shape flown in knife-edge, with a 1/4 roll
  on the entry and exit lines (as the knife-edge triangular loop). A roll
  phrase puts the same roll on both 45 degree lines.
"""

from __future__ import annotations

from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause

from .families import Modifiers, _is_plural, _polygon, _sense, family  # isort: skip


# The two 45 degree lines are equal and as long as the loops need for the
# figure to finish at its entry height.
CLOSING_LENGTH = "(2*loop_radius)"


def _cuban(
    name: str, mods: Modifiers, phrases: list[str], corners: list[Fraction], knife_edge: bool
) -> list[Clause]:
    rolls: dict[int, OlanRoll] = {}
    for phrase in phrases:
        if rolls or not _is_plural(phrase):
            raise F3AParseError(f"{name}: unexpected {phrase!r}")
        roll = require_roll(phrase)
        rolls = {1: roll, 2: roll}
    return _polygon(
        mods, _sense(mods), corners, rolls, knife_edge, {1: CLOSING_LENGTH, 2: CLOSING_LENGTH}
    )


_FORWARD = [Fraction(5, 8), Fraction(-3, 4), Fraction(1, 8)]
_REVERSE = [Fraction(1, 8), Fraction(-3, 4), Fraction(5, 8)]


@family("cuban eight", "knife-edge cuban eight")
def cuban_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _cuban(name, mods, phrases, _FORWARD, name.startswith("knife-edge"))


@family("reverse cuban eight", "knife-edge reverse cuban eight")
def reverse_cuban_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _cuban(name, mods, phrases, _REVERSE, name.startswith("knife-edge"))
