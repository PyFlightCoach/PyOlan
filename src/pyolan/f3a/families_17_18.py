"""F3A families, groups 17 (top hat) and 18 (humpty bump).

Conventions decided per family (checked against the USG drawings):

- top hat (17): entry, 1/4 loop up, a vertical upline, 1/4 loop, the top line
  flown forwards, 1/4 loop, a vertical downline, 1/4 loop out to the exit line.
  The corners are 1/4, 1/4, 1/4, 1/4 with the two at the top turning the other
  way (as the hourglass corners), and both vertical lines are the same length
  (one shared ``line_length``), so the figure finishes at its entry height.
  "from top" is the mirror image about the entry height (down first). The
  plural rolls ("2/4pt rolls", "2/2pt rolls") put the same roll centred on both
  vertical lines, as the drawings show (a 2/4pt roll on each line makes the top
  line inverted, a 2/2pt roll leaves it upright). A single roll phrase is an
  error.
- humpty bump (18): the figure as the drawings show it, in one sense: entry,
  1/4 loop up, a vertical upline, a 1/2 loop that goes back over the top,
  a vertical downline and a 1/4 loop out in the entry direction. The up and
  down lines are equal (one ``line_length``), so the figure finishes at its
  entry height. In the drawings the entry line runs to the first vertical line
  and the exit line starts at the second, so the two lines overlap between
  the legs (the drawing offsets the exit line a little to show it). "from top"
  is the mirror image (down first). The description gives one roll for each
  vertical line as "<roll> up" and "<roll> down", in either order; "up" is the
  line flown upwards and "down" the one flown downwards (from the bottom the up
  line is first, from the top the down line is first). Rolls are centred on the
  line, which is what the drawings show (an arrow, and a snap triangle, in the
  middle of each line). Both lines must be rolled.
- directions of the rolls and of the loops are the pilot's choice (the engine
  decides pull, push and the roll signs from the attitudes), as everywhere in F3A.
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause

from .families import Modifiers, _is_plural, _polygon, _sense, family  # isort: skip


@family("top hat")
def top_hat(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if len(phrases) != 1 or not _is_plural(phrases[0]):
        raise F3AParseError(f"{name}: expected rolls for both vertical lines, got {phrases!r}")
    roll = require_roll(phrases[0])
    corners = [Fraction(1, 4), Fraction(-1, 4), Fraction(-1, 4), Fraction(1, 4)]
    return _polygon(mods, _sense(mods), corners, {1: roll, 3: roll})


_UP_DOWN_RE = re.compile(r"^(?P<roll>.+?) (?P<dir>up|down)$")


@family("humpty bump")
def humpty_bump(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    by_direction: dict[str, OlanRoll] = {}
    for phrase in phrases:
        if not (match := _UP_DOWN_RE.match(phrase)) or match.group("dir") in by_direction:
            raise F3AParseError(f"{name}: unexpected {phrase!r}, expected a roll up and a roll down")
        by_direction[match.group("dir")] = require_roll(match.group("roll"))
    if set(by_direction) != {"up", "down"}:
        raise F3AParseError(f"{name}: expected a roll up and a roll down, got {phrases!r}")
    first, second = ("down", "up") if mods.start == "top" else ("up", "down")
    corners = [Fraction(1, 4), Fraction(1, 2), Fraction(1, 4)]
    return _polygon(
        mods, _sense(mods), corners, {1: by_direction[first], 2: by_direction[second]}
    )
