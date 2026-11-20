"""F3A families, group F (half Cuban eight and half reverse Cuban eight).

Conventions decided per family (checked against the USG drawings):

- half Cuban eight: the first half of the Cuban eight (see families_10.py): level
  entry, a 5/8 loop up and over, a 45 degree line down, and a 1/8 loop the other way
  back to level. The figure turns round: it exits level, flying back the way it came,
  and ends lower than the loop top. Unlike the whole Cuban eight it does not close
  (no closure expression: decided 2026-11-20, A4 review, any height that works is
  fine). The 45 degree line is the builder's default ``line_length`` (the shared
  comparison, with its roll and pads), not tied to the loop radius, so the layout sets
  the height: tight loops and a long line fly middle to bottom naturally, and bottom to
  middle only with very large loops and a short line (awkward). The line was tied to
  one loop radius before (the drawings show it about that long), which made middle to
  bottom unreachable once the levels were evenly spaced in metres. ``from top`` is the
  mirror image about the entry height (5/8 loop down, 45 degree line up).
  - ``<roll>`` / ``<roll> up`` (F.3-F.19): one roll centred on the 45 degree line;
    "up" is the direction of that line and is only given for ``from top`` (checked).
    The exit attitude follows from the roll and the loops (without a roll the figure
    flips: it is a half turn about the wings), the direction of the roll is the
    pilot's choice.
  - ``from <attitude> up|down with <roll> integrated in first 180 degree of loop,
    exit <attitude>`` (F.41-F.48): the roll (a full roll when no amount is given) is
    spread over the first half of the 5/8 loop, so the loop is built as a 1/2 loop
    carrying the roll and a 1/8 loop. The line has no roll. "up" starts at the
    bottom, "down" at the top (checked against nothing else: there is no ``from top``).
    "down" (F.45-F.48) is the top-to-bottom mirror of "up", as the drawings show and the
    A4 review confirmed (2026-11-20): from the entry down round a 5/8 loop, a 45 degree
    line UP and a 1/8 loop to level; the roll is over the first 180 degrees of the loop
    and finishes at the half-loop point, the last 45 degrees of loop has none. An upright
    pilot entering down is the mirror of an inverted one entering up (F.45 of F.42, F.46
    of F.41, F.47 of F.44, F.48 of F.43; pinned in the tests). The pairs the figure can fly
    are the mirror of the half Cuban's too (top to top, middle to middle, middle to top
    natural, top to middle awkward).
  - ``from <attitude> with 3 consecutive 1/4 rolls, 5/8 knife edge loop, 3/4 roll,
    exit <attitude>`` (F.49-F.52, F.57-F.60 ``from top <attitude>``): the three quarter
    rolls on the entry line (so, as every roll that starts a figure, a line follows
    them), the 5/8 loop in knife-edge flight, the 3/4 roll centred on the 45 degree
    line and then the 1/8 loop. Both rolls and the loop yaw are one mirror option:
    the exit attitude decides their relative direction (the figure is itself a half
    turn about the wings, so two 3/4 rolls the same way, 1 1/2 rolls, bring the
    pilot back to the entry attitude and opposite ones turn the pilot over).
- half reverse Cuban eight: the second half of the reverse Cuban eight, flown in
  the other order: 1/8 loop up, a 45 degree line up and a 5/8 loop over the top
  and down to level, again a turnaround. It starts one box height above where
  it finishes (middle to low). ``from top`` is the mirror image (down, high at the
  end). The roll is on the 45 degree line (``roll`` or ``roll down`` from top). The
  exit attitude follows from the roll (a plain half reverse Cuban eight flips, F.22).
  The knife-edge version (F.53-F.56, F.61-F.64) has its three quarter rolls on the
  45 degree line, the 5/8 loop in knife-edge flight and the 3/4 roll on the exit
  line (a roll that ends the figure follows a line); linked as above.
"""

from __future__ import annotations

import re
from fractions import Fraction

import schemas.positioning as p

from .errors import F3AParseError
from .rolls import require_roll
from .steps import Clause, Entry, Exit, Line, Loop, Roll

from .families import Modifiers, family  # isort: skip
from .families_a_c_d import _attitude_after, _check_total, _exit_attitude  # isort: skip

_FIVE_EIGHTHS = Fraction(5, 8)
_EIGHTH = Fraction(1, 8)
_HALF = Fraction(1, 2)

_ROLL_WAY_RE = re.compile(r"^(?P<roll>.+?)(?: (?P<way>up|down))?$")
_START_RE = re.compile(r"^from (?P<att>upright|inverted) (?P<way>up|down)$")
_INTEGRATED_RE = re.compile(
    r"^(?:(?P<roll>.+?) )?integrated in first 180 degree of loop$"
)
_KE_LOOP = "5/8 knife-edge loop"

def _check_plain_start(name: str, mods: Modifiers) -> None:
    if mods.start not in (None, "top") or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: a start at {mods.start!r} is not supported")


def _line_direction(reverse: bool, sense: int) -> str:
    """The direction of the 45 degree line: down for a half Cuban eight from the
    bottom (the loop goes up and over), up for a reverse one."""
    return "up" if (sense == 1) == reverse else "down"


def _line(sense: int, reverse: bool) -> Line:
    """The 45 degree line, after the first loop (1/8 for reverse, 5/8 otherwise)."""
    amount = _EIGHTH if reverse else _FIVE_EIGHTHS
    return Line(frozenset({(amount * sense) % 1}), label="45 degree line")


def _plain(name: str, mods: Modifiers, phrases: list[str], reverse: bool) -> list[Clause]:
    _check_plain_start(name, mods)
    sense = -1 if mods.start == "top" else 1
    rolls: list[Clause] = []
    if len(phrases) > 1:
        raise F3AParseError(f"{name}: expected one roll, got {phrases!r}")
    if phrases:
        match = _ROLL_WAY_RE.match(phrases[0])
        if way := match.group("way"):
            expected = _line_direction(reverse, sense)
            if way != expected or mods.start != "top":
                raise F3AParseError(
                    f"{name}: the 45 degree line of a figure from {mods.start or 'bottom'} "
                    f"goes {expected}, got {phrases[0]!r}"
                )
        rolls = [Roll(require_roll(match.group("roll")))]
    first, second = (_EIGHTH, _FIVE_EIGHTHS) if reverse else (_FIVE_EIGHTHS, _EIGHTH)
    return [
        Entry(mods.entry),
        Loop(first, sense=sense),
        _line(sense, reverse),
        *rolls,
        Loop(second, sense=-sense),
        Exit(mods.exit),
    ]


def _integrated(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    if mods.start is not None or mods.first or mods.entry_form:
        raise F3AParseError(f"{name}: no start height expected, it follows 'up' or 'down'")
    if len(phrases) not in (2, 3):
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    start, integrated, *rest = phrases
    match = _START_RE.match(start)
    if not match:
        raise F3AParseError(f"{name}: expected 'from <attitude> up|down', got {start!r}")
    if mods.entry != p.Orientation.UPRIGHT:
        raise F3AParseError(f"{name}: the entry attitude is given twice")
    entry = _attitude_after(name, mods, f"from {match.group('att')}")
    sense = 1 if match.group("way") == "up" else -1
    exit_attitude = _exit_attitude(name, mods, rest)
    if not (found := _INTEGRATED_RE.match(integrated)):
        raise F3AParseError(f"{name}: expected a roll 'integrated in first 180 degree of loop'")
    roll = require_roll(found.group("roll") or "roll")
    return [
        Entry(entry),
        Loop(_HALF, sense=sense, roll=roll, integrated=True),
        Loop(_EIGHTH, sense=sense),
        _line(sense, False),
        Loop(_EIGHTH, sense=-sense),
        Exit(exit_attitude),
    ]


def _knife_edge(name: str, mods: Modifiers, phrases: list[str], reverse: bool) -> list[Clause]:
    _check_plain_start(name, mods)
    if len(phrases) not in (4, 5):
        raise F3AParseError(f"{name}: unexpected {phrases!r}")
    start, first, loop, last, *rest = phrases
    entry = _attitude_after(name, mods, start)
    if loop != _KE_LOOP:
        raise F3AParseError(f"{name}: expected {_KE_LOOP!r}, got {loop!r}")
    exit_attitude = _exit_attitude(name, mods, rest)
    rolls = []
    for phrase in (first, last):
        roll = require_roll(phrase)
        _check_total(name, roll, 0.75, phrase)
        rolls.append(roll)
    sense = -1 if mods.start == "top" else 1
    if reverse:
        return [
            Entry(entry),
            Loop(_EIGHTH, sense=sense, knife_edge=False),
            _line(sense, True),
            Roll(rolls[0]),
            Loop(_FIVE_EIGHTHS, sense=-sense, knife_edge=True),
            Roll(rolls[1]),
            Exit(exit_attitude),
        ]
    return [
        Entry(entry),
        Roll(rolls[0]),
        Loop(_FIVE_EIGHTHS, sense=sense, knife_edge=True),
        _line(sense, False),
        Roll(rolls[1]),
        Loop(_EIGHTH, sense=-sense, knife_edge=False),
        Exit(exit_attitude),
    ]


def _build(name: str, mods: Modifiers, phrases: list[str], reverse: bool) -> list[Clause]:
    if any(_INTEGRATED_RE.match(phrase) for phrase in phrases):
        if reverse:
            raise F3AParseError(f"{name}: an integrated roll is only described for the forward figure")
        return _integrated(name, mods, phrases)
    if any("knife-edge loop" in phrase for phrase in phrases):
        return _knife_edge(name, mods, phrases, reverse)
    return _plain(name, mods, phrases, reverse)


@family("half cuban eight")
def half_cuban_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _build(name, mods, phrases, reverse=False)


@family("half reverse cuban eight")
def half_reverse_cuban_eight(name: str, mods: Modifiers, phrases: list[str]) -> list[Clause]:
    return _build(name, mods, phrases, reverse=True)
