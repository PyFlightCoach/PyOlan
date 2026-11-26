"""A figure's elements from OpenAero's drawing string (plan Phase D, D10).

OpenAero draws each catalogue figure from a drawing string (``data/openaero_figures.json``,
the second item of each variant), walked by buildFigure (js/main.js). The direction
port (direction.py) walks the same string for the direction state and K; this module
turns it into PyOlan's elements, so the geometry is the figure OpenAero draws for the
variant it chooses, including the attitude markers, the inverted forms and the roll
that selects a variant.

The drawing characters (OpenAero's figpat and drawAngles, js/config.js):

* ``d v z m c p r o`` and upper case: a corner or curve of 45 to 360 degrees, pull
  positive, upper case pushed. The signs are the aircraft's: after a half roll a pull
  is still positive. ``=`` (draw as a curve), ``/`` (half size), ``«`` and ``»``
  (drawing hints) do not change the flight.
* ``!`` after a curve: the next roll is in the top of it.
* ``~`` and ``'``: lines. ``_``: a roll slot on the line it is drawn on.
* ``h`` / ``H``: a hammer (stall turn). ``t`` / ``T``: a tailslide, wheels down (``ta``)
  or canopy down (``ita``).
* ``4``: a fixed quarter roll where it is drawn (between the curves of ``oj``, ``mj``,
  ``aj``); its direction is chosen like any quarter roll on a vertical line.
* ``-`` at the start: an inverted entry, nothing to draw.

PyOlan's elements follow the hand-written primitives (primitives.py) so that a figure
that already agreed with OpenAero keeps the same elements and element names:

* consecutive curves pulled the same way are one loop (``v=m!`` is the 3/4 loop of
  ``ao``), a change of sign starts a new one (``mm``, ``oo``);
* a loop with a roll in its top can roll (the roll is centred on its apex);
* a line with a roll slot can roll; a line between two elements without one is an
  unjudged line; the entry and exit lines are kept only when they have a roll slot.

* a roll slot drawn between two curves with no line (``d=_d=``) is a bare roll point:
  a roll there is flown on a short line, an empty one is no element at all.

Turns (``j``), point tips (``u``) and two roll slots on one line are not drawn here:
elements_from_draw returns None and the figure keeps its hand-written primitive.
"""

from __future__ import annotations

from .direction import DRAW_ANGLES
from .primitives import OlanEl, lo, st, ts

_LINES = frozenset("~'")
_HINTS = frozenset("=/«»-")


FIXED_QUARTER = "4"  # the slot of a fixed quarter roll


def elements_from_draw(draw: str) -> tuple[list[OlanEl], list[int | str | None]] | None:
    """The elements of a drawing string, and for each element the roll slot it
    holds: the number of the ``_`` in the string (0 for the first), FIXED_QUARTER for
    a fixed quarter roll, or None.

    Returns None for a drawing string with something this module does not draw.
    """
    oels: list[OlanEl] = []
    slots: list[int | str | None] = []
    run = False  # a line is being drawn
    drawn_line = False  # the line has line characters, not only a slot
    run_slot: int | str | None = None
    k = 0

    def end_line(last: bool = False) -> None:
        nonlocal run, run_slot, drawn_line
        if run_slot is not None:
            oels.append(OlanEl("Line", 0, True, bare=not drawn_line))
            slots.append(run_slot)
        elif run and oels and not last:
            oels.append(OlanEl("Line", 0, False))
            slots.append(None)
        run, run_slot, drawn_line = False, None, False

    i, n = 0, len(draw)
    while i < n:
        c = draw[i]
        if c in _LINES:
            run = drawn_line = True
        elif c == "_" or c == FIXED_QUARTER:
            if run_slot is not None:
                return None
            run = True
            if c == "_":
                run_slot = k
                k += 1
            else:
                run_slot = FIXED_QUARTER
        elif c in DRAW_ANGLES:
            end_line()
            amount = DRAW_ANGLES[c] / 360
            top = i + 1 < n and draw[i + 1] == "!"
            if top and not (i + 2 < n and draw[i + 2] == "_"):
                return None
            previous = oels[-1] if oels else None
            if (
                previous is not None
                and previous.kind == "Loop"
                and (previous.loopamount > 0) == (amount > 0)
                and not (top and slots[-1] is not None)
            ):
                oels[-1] = lo(previous.loopamount + amount, previous.canRoll or top)
            else:
                oels.append(lo(amount, top))
                slots.append(None)
            if top:
                slots[-1] = k
                k += 1
                i += 2  # past "!" and the slot it fills
        elif c in "hH":
            end_line()
            oels.append(st())
            slots.append(None)
        elif c in "tT":
            end_line()
            oels.append(ts(1 if c == "t" else -1))
            slots.append(None)
        elif c not in _HINTS:
            return None
        i += 1
    end_line(last=True)
    while oels and oels[0].kind == "Line" and slots[0] is None:
        oels.pop(0)
        slots.pop(0)
    return oels, slots
