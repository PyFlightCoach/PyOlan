"""F3A families, lettered group N (half square loop on corner with rolls on the legs).

- half square loop on corner (N): half of the square loop on corner (06, but with
  two legs): entry, a 1/8 loop, a 45 degree leg, a 1/4 loop, a second 45 degree leg
  and a 1/8 loop out, flying back the way it came (a turnaround). The drawings put
  the entry and exit on the same side, so the figure starts low and finishes high
  ("up", sense +1) or the reverse ("down", sense -1), like the half square loop of
  group A: that height difference is the figure's definition. The two legs are
  equal (one shared line length).
  - ``from <attitude> up|down`` gives the entry attitude and the sense ("down" is
    flown from the top). ``<roll> on first leg``, ``<roll> on second leg``: each roll is
    centred on its leg. A bare ``snap roll`` is one whole snap roll.
  - The USG list writes "11/4" for "1 1/4" (a rulebook PDF artefact, read as 1 1/4 by
    normalise.py).
  - Roll directions: quarter rolls and rolls of an odd number of quarters (1/4, 3/4,
    1 1/4) leave the wings vertical, so the corner between the legs is a yaw loop
    (knife-edge) and the exit attitude is decided by the relative direction of the two
    rolls (the two of them are one mirror option: only both together can be
    mirrored). Whole and half rolls and snaps leave their direction to the pilot.
"""

from __future__ import annotations

import re
from fractions import Fraction

from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause

from .families import Modifiers, _polygon, family  # isort: skip
from .families_a_c_d import _ATTITUDE, _exit_attitude  # isort: skip

_FROM_RE = re.compile(r"^from (?P<att>upright|inverted) (?P<dir>up|down)$")
_LEG_RE = re.compile(r"^(?P<roll>.+?) on (?P<leg>first|second) leg$")
_LEGS = {"first": 1, "second": 2}


@family("half square loop on corner")
def half_square_loop_on_corner(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: a start at {mods.start!r} is not supported")
    if len(phrases) not in (3, 4) or not (start := _FROM_RE.match(phrases[0])):
        raise F3AParseError(f"{name}: expected 'from <attitude> up|down' and a roll on each leg, got {phrases!r}")
    if mods.entry != _ATTITUDE["upright"]:
        raise F3AParseError(f"{name}: the entry attitude is given twice")
    rolls = {}
    for phrase in phrases[1:3]:
        if not (match := _LEG_RE.match(phrase)) or _LEGS[match.group("leg")] in rolls:
            raise F3AParseError(f"{name}: expected a roll on each leg, got {phrase!r}")
        rolls[_LEGS[match.group("leg")]] = require_roll(match.group("roll"))
    mods.entry = _ATTITUDE[start.group("att")]
    mods.exit = _exit_attitude(name, mods, phrases[3:])
    sense = 1 if start.group("dir") == "up" else -1
    eighth, quarter = Fraction(1, 8), Fraction(1, 4)
    return _polygon(mods, sense, [eighth, quarter, eighth], rolls)
