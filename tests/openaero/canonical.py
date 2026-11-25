"""Canonical form of a figure, for comparing PyOlan with OpenAero.

Both sides are reduced to a list of segments:

* ``["arc", degrees, rolls]``: consecutive arcs merged, pull positive. ``degrees``
  is ``None`` where PyOlan's spin element replaces the arc before the spin (a
  wildcard that matches any angle).
* ``["line", rolls]``: consecutive lines and the rolls on them.
* ``["stall"]``: a stall turn (OpenAero's hammer).
* ``["tail", +1 | -1]``: a tailslide, +1 wheels down (``ta``), -1 canopy down
  (``ita``).
* ``["turn", degrees, rolls]``: a turn or rolling turn. Each roll's sign is +1
  when it rolls towards the inside of the turn.
* ``["other", name]``: a shape PyOlan does not build (non-Aresti shapes).

A roll is ``[kind, degrees, sign]``: kind ``roll``, ``snap`` or ``spin``, unsigned
degrees, and the sign relative to the first roll of its segment (turns: relative
to the turn). Consecutive pieces of the same kind and sign are merged, so a point
roll equals the same amount rolled in one go.

Entry and exit lines without rolls are dropped, and so are OpenAero's roll gap
placeholders (lines shorter than 0.5). The form ignores line lengths, roll
positions within a line, absolute roll direction, point-roll stops and the
negative flag of snaps and spins (see ``oa_negatives``).

OpenAero's side comes from the buildShape trace recorded by
``tools/openaero/oa-trace.js``. PyOlan's side comes from ``OlanFig.create_elements``,
which is what the builder receives.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

ROLL_KINDS = {"Roll": "roll", "Snap": "snap", "Spin": "spin"}
PE_ROLL_TYPES = {"r": "roll", "s": "snap", "-": "spin"}
PE_ROLL_WORDS = {"roll": "roll", "snap": "snap", "spin": "spin"}
GAP = 0.5  # OpenAero lines shorter than this are roll gap placeholders
NON_ARESTI_SHAPES = {"ShoulderRoll", "Ruade", "Lomcevak", "PointTip"}


# ---------------------------------------------------------------------------
# rolls


def merge_rolls(rolls: Iterable[tuple[str, float]]) -> list[list]:
    """[(kind, signed degrees)] -> [[kind, |degrees|, sign relative to the first]].

    Consecutive aileron roll pieces with the same sign are merged.
    """
    merged: list[list] = []
    for kind, deg in rolls:
        if (
            merged
            and kind == "roll"
            and merged[-1][0] == "roll"
            and math.copysign(1, merged[-1][1]) == math.copysign(1, deg)
        ):
            merged[-1][1] += deg
        else:
            merged.append([kind, deg])
    if not merged:
        return []
    first = math.copysign(1, merged[0][1])
    return [
        [kind, round(abs(deg)), int(math.copysign(1, deg) * first)]
        for kind, deg in merged
    ]


# ---------------------------------------------------------------------------
# tokens -> segments (shared by both sides)


def _segments(tokens: list[list], flip_after_inverting_roll: bool) -> list[list]:
    """Merge raw tokens into segments.

    Tokens: ["arc", deg | None], ["roll", kind, deg, embedded], ["line"],
    ["stall"], ["tail", dir], ["turn", deg, rolls], ["other", name].

    A roll marked embedded (rolled in a loop) is part of the arc around it.
    OpenAero signs arcs by its drawing (pull or push from the current attitude),
    so after an embedded roll that inverts, the rest of that loop changes sign
    (flip_after_inverting_roll). PyOlan's loop keeps its own sign.
    """
    out: list[list] = []
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        if t[0] == "arc" or (t[0] == "roll" and t[3]):
            total: float | None = 0.0
            emb: list[tuple[str, float]] = []
            body = 1
            rolled = 0.0
            j = i
            while j < n:
                tj = tokens[j]
                if tj[0] == "arc":
                    if tj[1] is None or total is None:
                        total = None
                    else:
                        total += body * tj[1]
                    j += 1
                elif tj[0] == "roll" and tj[3]:
                    emb.append((tj[1], tj[2]))
                    if flip_after_inverting_roll:
                        rolled += tj[2]
                        body = -1 if round(abs(rolled)) % 360 == 180 else 1
                    j += 1
                else:
                    break
            out.append(["arc", None if total is None else round(total), merge_rolls(emb)])
            i = j
        elif t[0] in ("line", "roll"):
            rolls: list[tuple[str, float]] = []
            j = i
            while j < n and (tokens[j][0] == "line" or (tokens[j][0] == "roll" and not tokens[j][3])):
                if tokens[j][0] == "roll":
                    rolls.append((tokens[j][1], tokens[j][2]))
                j += 1
            out.append(["line", merge_rolls(rolls)])
            i = j
        else:
            out.append(list(t))
            i += 1
    if out and out[0] == ["line", []]:
        out = out[1:]
    if out and out[-1] == ["line", []]:
        out = out[:-1]
    return out


# ---------------------------------------------------------------------------
# OpenAero


def _oa_turn(draw: str, attitude: float) -> list:
    """A makeTurn draw string ("j2", "J11", "jio215") -> ["turn", deg, rolls].

    The first digit is the turn in quarters, the rest the rolls ("5" a half roll,
    any other digit that many full rolls). Upper case J starts with an outside roll
    when upright; inverted, the drawing is mirrored (makeTurn, rollDir).
    "io" alternates the roll direction.
    """
    numbers = re.sub(r"[^\d]", "", draw)
    extent = int(numbers[0]) * 90
    inward = ("J" in draw) == (attitude == 180)
    alternate = bool(re.search(r"io|IO", draw))
    rolls: list[tuple[str, float]] = []
    sign = 1 if inward else -1
    for d in numbers[1:]:
        for amount in [180] if d == "5" else [360] * int(d):
            rolls.append(("roll", sign * amount))
            if alternate:
                sign = -sign
    return ["turn", extent, turn_rolls(rolls)]


def turn_rolls(rolls: Iterable[tuple[str, float]]) -> list[list]:
    """[(kind, signed degrees)], positive inwards -> [[kind, |deg|, sign]].

    Consecutive rolls of the same kind and sign are merged. Unlike merge_rolls the
    sign stays relative to the turn (+1 inwards), not to the first roll.
    """
    merged: list[list] = []
    for kind, deg in rolls:
        sign = 1 if deg > 0 else -1
        if merged and merged[-1][0] == kind and merged[-1][2] == sign:
            merged[-1][1] += abs(deg)
        else:
            merged.append([kind, abs(deg), sign])
    return [[k, round(d), s] for k, d, s in merged]


def oa_tokens(trace: list[dict]) -> list[list]:
    tokens: list[list] = []
    for t in trace:
        s, prm = t["shape"], t["params"]
        if s == "Line":
            if isinstance(prm, list) and len(prm) > 2 and prm[2] == "hiddenCurve":
                continue
            if isinstance(prm, list) and isinstance(prm[0], (int, float)) and abs(prm[0]) < GAP:
                continue
            tokens.append(["line"])
        elif s in ("Curve", "Corner"):
            ang = prm["angle"] if isinstance(prm, dict) else prm
            tokens.append(["arc", float(ang)])
        elif s in ROLL_KINDS:
            top = bool(prm[2]) if len(prm) > 2 else False
            tokens.append(["roll", ROLL_KINDS[s], float(prm[0]), top])
        elif s == "Hammer":
            tokens.append(["stall"])
        elif s == "Tailslide":
            tokens.append(["tail", -1 if prm == "T" else 1])
        elif s == "Turn":
            tokens.append(_oa_turn(prm, t["att0"]))
        elif s in NON_ARESTI_SHAPES:
            tokens.append(["other", s])
        # RollTopLine and TurnRoll are drawing only
    return tokens


def oa_canonical(trace: list[dict]) -> list[list]:
    return _segments(oa_tokens(trace), flip_after_inverting_roll=True)


def oa_negatives(trace: list[dict]) -> list[list]:
    """[[kind, negative]] for every snap and spin, in order."""
    return [
        [ROLL_KINDS[t["shape"]], bool(t["params"][1])]
        for t in trace
        if t["shape"] in ("Snap", "Spin")
    ]


def oa_corrections(trace: list[dict]) -> list[int]:
    """Extents of the correction rolls OpenAero inserted (Roll params[4])."""
    return [
        round(t["params"][0])
        for t in trace
        if t["shape"] == "Roll" and len(t["params"]) > 4 and t["params"][4]
    ]


# ---------------------------------------------------------------------------
# PyOlan


def _pe_rolls(value: Any, rolltypes: Any) -> list[tuple[str, float]]:
    """A roll argument as the builder receives it -> [(kind, signed degrees)].

    value is radians (a number or a list), or "NxM" for N points of 1/M.
    rolltypes is "roll", "snap", "spin" or one character per point (r, s, -).
    """
    if isinstance(value, str):
        m = re.fullmatch(r"(\d+)x(-?\d+)", value)
        if not m:
            raise ValueError(f"cannot read roll argument {value!r}")
        values = [360 / int(m.group(2))] * int(m.group(1))
    else:
        values = [math.degrees(v) for v in (value if isinstance(value, (list, tuple)) else [value])]
    if rolltypes in PE_ROLL_WORDS or rolltypes is None:
        kinds = [PE_ROLL_WORDS.get(rolltypes, "roll")] * len(values)
    else:
        kinds = [PE_ROLL_TYPES[c] for c in rolltypes]
        if len(kinds) != len(values):
            raise ValueError(f"rolltypes {rolltypes!r} do not match {value!r}")
    return list(zip(kinds, values))


def _is_bank(pe) -> bool:
    return pe.kind == "roll" and pe.kwargs.get("padded") is False and not pe.kwargs.get("rolltypes")


def py_tokens(pes: list) -> list[list]:
    """The elements from OlanFig.create_elements() -> raw tokens."""
    tokens: list[list] = []
    skip: set[int] = set()
    for i, pe in enumerate(pes):
        if i in skip:
            continue
        kw = pe.kwargs
        if pe.kind == "loop" and kw.get("ke"):
            # a turn: a loop flown in the horizontal plane. A plain turn has a bank
            # roll element either side of it (TURN_BANK).
            deg = math.degrees(pe.args[0])
            rolls = []
            if kw.get("rolls") is not None:
                rolls = turn_rolls(
                    (k, v if deg > 0 else -v)
                    for k, v in _pe_rolls(kw["rolls"], kw.get("rolltypes"))
                )
            else:
                if tokens and tokens[-1][0] == "_bank":
                    tokens.pop()
                if i + 1 < len(pes) and _is_bank(pes[i + 1]):
                    skip.add(i + 1)
            tokens.append(["turn", round(abs(deg)), rolls])
        elif pe.kind == "loop":
            tokens.append(["arc", math.degrees(pe.args[0])])
            if kw.get("rolls") is not None:
                for k, v in _pe_rolls(kw["rolls"], kw.get("rolltypes")):
                    tokens.append(["roll", k, v, True])
        elif pe.kind == "line":
            tokens.append(["line"])
        elif pe.kind == "roll":
            if _is_bank(pe) and i + 1 < len(pes) and pes[i + 1].kind == "loop" and pes[i + 1].kwargs.get("ke"):
                tokens.append(["_bank"])
                continue
            tokens.append(["line"])
            for k, v in _pe_rolls(pe.args[0], kw.get("rolltypes")):
                tokens.append(["roll", k, v, False])
            tokens.append(["line"])
        elif pe.kind == "spin":
            # PyOlan's spin element replaces the arc before the spin line
            tokens.append(["arc", None])
            tokens.append(["line"])
            tokens.append(["roll", "spin", math.degrees(pe.args[0]), False])
        elif pe.kind == "snap":
            tokens.append(["line"])
            tokens.append(["roll", "snap", math.degrees(pe.args[0]), False])
        elif pe.kind == "stallturn":
            tokens.append(["stall"])
        elif pe.kind == "tailslide":
            direction = pe.args[0] if pe.args else pe.kwargs.get("direction", 1)
            tokens.append(["tail", 1 if direction > 0 else -1])
        else:
            tokens.append(["other", pe.kind])
    return [t for t in tokens if t[0] != "_bank"]


def py_canonical(pes: list) -> list[list]:
    return _segments(py_tokens(pes), flip_after_inverting_roll=False)


def py_negatives(olanfig) -> list[list]:
    """[[kind, negative]] for every snap and spin PyOlan parsed, in order."""
    out = []
    for r in olanfig.element_rolls():
        if r is None:
            continue
        out.extend([x.kind, bool(x.negative)] for x in r.roll_arr if x.kind != "roll")
    return out


# ---------------------------------------------------------------------------
# comparison


def segments_equal(a: list, b: list) -> bool:
    """Segment lists equal, with None arc angles matching any angle."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x[0] != y[0]:
            return False
        if x[0] == "arc":
            if x[1] is not None and y[1] is not None and x[1] != y[1]:
                return False
            if x[2] != y[2]:
                return False
        elif x != y:
            return False
    return True
