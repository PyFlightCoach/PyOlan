"""F3A families, lettered groups G (spins) and H (stall turns).

Both are turnaround versions of numbered families: G of the group 19 spins, H of the
group 20 stall turn. They reuse those builders (``families_19.spin`` and
``families_20.stall_turn``), which read ``Modifiers.forward`` (False for a lettered
group) to fly the figure back the way it came.

- G.1-G.4 ("two turn spin", "2 1/2 turn spin"): the spin, a short downline and a
  1/4 loop out flown the other way round, so the exit goes back. The exit attitude
  follows from the turns, as in group 19: whole turns and a push leave inverted
  ("two turn spin" exits inverted), 2 1/2 turns leave upright.
- G.5-G.8 ("2 1/4 turn spin, 1/4 loop with 1/4 roll integrated"): as 19.9-19.12, the
  loop in knife-edge with the quarter roll integrated, flown back.
- H.3-H.16: the group 20 stall turn (verticals of their own length, chosen by the
  layout, a roll centred on each line), with the exit loop flown back. The exit attitude is not
  in the words: it follows the rolls (see ``families_20._default_exit``). The
  catalogue's H.14 has no comma between its two rolls.
"""

from __future__ import annotations

from fractions import Fraction

from . import families_19
from .families import family  # isort: skip
from .families_19 import spin

# G.1 is the one new name: group 19 has no plain two turn spin
families_19._SPINS["two turn spin"] = (Fraction(2), False)
family("two turn spin")(spin)
