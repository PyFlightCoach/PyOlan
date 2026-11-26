"""A port of OpenAero's direction state, giving the exit direction of each figure.

OpenAero tracks four values while it draws a sequence:

* ``direction``: 0 = left to right (LTR), 90 = front to back, 180 = right to left
  (RTL), 270 = back to front. This is the drawing direction.
* ``attitude``: 0 upright, 180 inverted, 90 / 270 vertical up / down.
* ``go_right`` and ``go_front``: which way the next vertical 1/4 roll (or 3/4 etc.)
  turns when it returns to the X axis or the Y axis.

The physical heading of the aircraft is the direction, reversed when the attitude
is 180 (inverted).

The functions here mirror OpenAero (js/main/*.js); each one names the function and
the area it follows. Only what affects direction, attitude, ``go_right`` and
``go_front`` is ported. Drawing, K factors, alerts and the OLAN autocorrections
(``OLANXSwitch``, ``bumpBugCheck``) are not, because OpenAero does not run the
autocorrections when it opens a file. The figure drawing strings come from
OpenAero's figure table (``data/openaero_figures.json``, see
``scripts/generate_openaero_figures.py``).

Known limits (they only matter for sequences that rely on them):

* non-Aresti rolls are kept, OpenAero drops them unless "non-Aresti rolls" is set;
* the Y axis flip ``/`` and user-built figures are not handled.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files

import schemas.positioning as p

# OA.drawAngles (js/config.js)
DRAW_ANGLES = {
    "d": 45, "v": 90, "z": 135, "m": 180, "c": 225, "p": 270, "r": 315, "o": 360,
    "D": -45, "V": -90, "Z": -135, "M": -180, "C": -225, "P": -270, "R": -315,
    "O": -360,
}  # fmt: skip

_ROLL_TYPES = {"_": 1, "^": 2, "&": 3, "$": 4, "~": 9}  # figpat -> fig.rolls
_TURNS_AND_ROLLS = re.compile(r"[\d\(\)\^_&$~]+")  # regexTurnsAndRolls
_ROLL_BEFORE_BASE = re.compile(r"^[+-][\^_&$~]")  # regexRollBeforeBase


@lru_cache
def _figure_table() -> dict[str, list[list[str]]]:
    return json.loads(files("pyolan.data").joinpath("openaero_figures.json").read_text())


@lru_cache
def _k_table() -> dict:
    """OpenAero's K tables (data/openaero_k.json, written by tools/openaero/export.py):
    bases[base][variant] = [pattern, aresti, k powered, k glider] in the order of
    _figure_table(), and rolls[attitude prefix + roll pattern] = [aresti, k powered,
    k glider]."""
    return json.loads(files("pyolan.data").joinpath("openaero_k.json").read_text())


# rollAttitudes (js/config.js): the roll K table prefix for each attitude
ROLL_ATTITUDES = {0: "", 45: "d", 90: "v", 135: "d", 180: "", 225: "id", 270: "iv", 315: "id"}


def _glider_k(powered: int, glider: int | None) -> int:
    """OpenAero uses the glider K when it is set, and the powered K otherwise."""
    return glider if glider else powered


def _js_mod(a: float, b: float) -> float:
    """JavaScript's % (the sign follows the dividend)."""
    return math.fmod(a, b)


def _js_int(x: float) -> int:
    """JavaScript parseInt on a number (truncate towards zero)."""
    return int(x)


@dataclass
class FigureDirection:
    """What OpenAero says about one figure."""

    entry_direction: int
    entry_attitude: int
    exit_direction: int
    exit_attitude: int
    resolved: bool = True
    token: str = ""
    switch_x: bool = False
    switch_y: bool = False
    # OpenAero's aresti numbers and K (base plus rolls, rule-free); None unresolved
    aresti: list[str] = field(default_factory=list)
    k_powered: int | None = None
    k_glider: int | None = None
    # the roll slots of the figure (OpenAero fig.rolls: 0 none, 1 full, 2 half,
    # 3 any, 4 any or spin, 9 line) and the correction rolls OpenAero inserts, as
    # (slot, signed degrees) (D1)
    roll_slots: list[int] = field(default_factory=list)
    corrections: list[tuple[int, int]] = field(default_factory=list)
    # the attitude (0 upright, 180 inverted) the figure before ended in, when this
    # figure is written to start in the other one; OpenAero autocorrects such a
    # join, parse_olan raises (D2)
    entry_conflict: int | None = None

    @staticmethod
    def _physical(direction: int, attitude: int) -> int:
        return (direction + (180 if attitude == 180 else 0)) % 360

    @property
    def entry_axis(self) -> str:
        return "X" if self.entry_direction % 180 == 0 else "Y"

    @property
    def exit_axis(self) -> str:
        return "X" if self.exit_direction % 180 == 0 else "Y"

    @property
    def exit_physical(self) -> int:
        return self._physical(self.exit_direction, self.exit_attitude)

    @property
    def entry_physical(self) -> int:
        return self._physical(self.entry_direction, self.entry_attitude)

    def exit_heading(self, wind: p.Heading = p.Heading.LTOR) -> p.Heading:
        return physical_to_heading(self.exit_physical, wind)

    def entry_heading(self, wind: p.Heading = p.Heading.LTOR) -> p.Heading:
        return physical_to_heading(self.entry_physical, wind)


def physical_to_heading(physical: int, wind: p.Heading = p.Heading.LTOR) -> p.Heading:
    """Map OpenAero's physical direction onto a Heading.

    OpenAero draws "eu" (upwind) as direction 0 and "ed" as 180. PyOlan's wind is
    the downwind heading, so 180 maps onto it. Angles run anticlockwise seen from
    above in OpenAero and clockwise in a Heading, so the rest follows by reflection:
    front to back (90) is a left turn from LTR, which is OUTTOIN when going LTOR.
    """
    yaw = (wind.value + math.pi - math.radians(physical)) % (2 * math.pi)
    return p.Heading.infer(yaw)


def heading_to_physical(heading: p.Heading, wind: p.Heading = p.Heading.LTOR) -> int:
    return int(round(math.degrees(wind.value + math.pi - heading.value))) % 360


@dataclass
class _Roll:
    """One rolling element of a roll slot (OpenAero roll[i][j] of type != line).

    kind is OpenAero's type (roll, possnap, negsnap, posspin, negspin, slowroll or
    other for the non-Aresti shoulder roll, ruade and lomcevak) and pattern the roll
    text OpenAero looks its K up with ("24", "3if", "1f" for a bare "f").
    """

    extent: float
    kind: str = "roll"
    pattern: str = ""


_SUFFIX_KINDS = {"f": "snap", "s": "spin", "e": "other", "u": "other", "l": "other"}


def _suffix_kind(letter: str, negative: bool) -> str:
    kind = _SUFFIX_KINDS[letter]
    if kind == "other":
        return kind
    return ("neg" if negative else "pos") + kind


def parse_rolls(pattern: str) -> tuple[list[_Roll], int]:
    """Parse one roll slot into its rolling elements and total extent (degrees).

    Mirrors the roll pattern parser at the top of buildFigure
    (js/main/14-figures.js). Lines (. ' ` and so on) are not kept, only the rolls.
    The first roll has a positive sign, ',' reverses it and ';' keeps it.
    """
    rolls: list[_Roll] = []
    total = 0
    sign = 1
    j = 0
    in_comment = False
    while j < len(pattern):
        ch = pattern[j]
        if in_comment:
            in_comment = ch != '"'
            j += 1
            continue
        if ch == '"':
            in_comment = True
        elif ch == ",":
            sign = -sign
        elif ch in "fsleu":
            rolls.append(_Roll(sign * 360, _suffix_kind(ch, False), "1" + ch))
            total += sign * 360
        elif ch == "i" and j + 1 < len(pattern) and pattern[j + 1] in "fseul":
            j += 1
            rolls.append(_Roll(sign * 360, _suffix_kind(pattern[j], True), "1i" + pattern[j]))
            total += sign * 360
        elif ch in "123456789":
            start = j
            nxt = pattern[j + 1] if j + 1 < len(pattern) else ""
            nxt2 = pattern[j + 2] if j + 2 < len(pattern) else ""
            stops = 0
            if ch == "9":
                extent = 720.0
            elif nxt and nxt in "012345678":
                if nxt2 and nxt2 in "123456789":
                    stops = int(nxt2)
                    extent = int(pattern[j : j + 2]) * (360 / stops)
                    j += 1
                elif nxt != "0":
                    stops = int(nxt)
                    extent = int(ch) * (360 / stops)
                else:
                    extent = 0.0
                j += 1
            elif ch == "1":
                extent = 360.0
            elif ch == "4":
                extent = 90.0
            elif ch == "8":
                stops = 8
                extent = 90.0
            else:
                extent = 90.0 * int(ch)
            # an optional i/f/s/e/u/l after the roll (snap, spin ...)
            nxt = pattern[j + 1] if j + 1 < len(pattern) else ""
            suffix = False
            kind = "roll"
            if nxt == "i" and j + 2 < len(pattern) and pattern[j + 2] in "fseul":
                kind = _suffix_kind(pattern[j + 2], True)
                j += 2
                suffix = True
            elif nxt and nxt in "fseul":
                kind = _suffix_kind(nxt, False)
                j += 1
                suffix = True
            if suffix and stops:
                extent = 0.0  # OpenAero rejects snaps and spins with stops
            if extent:
                rolls.append(_Roll(sign * extent, kind, pattern[start : j + 1]))
                total += sign * extent
        elif ch == "0":
            nxt = pattern[j + 1] if j + 1 < len(pattern) else ""
            extent = {"2": 180, "1": 360, "6": 540}.get(nxt, 0)
            j += 1
            if extent:
                rolls.append(_Roll(sign * extent, "slowroll", "0" + nxt))
                total += sign * extent
        j += 1
    return rolls, total


def _fig_rolls(pattern: str, base: str) -> list[int]:
    """OA.fig[n].rolls: the type of each roll slot (04-complex-shapes.js, ~4130)."""
    bare = re.sub(r"[+-]+", "", base)
    rollbase = pattern.split(bare) if bare else [re.sub(r"[+-]+", "", pattern)]
    slots = re.sub(r"[\(\+\-]+", "", ")".join(rollbase)).split(")")
    return [_ROLL_TYPES.get(s, 0) for s in slots]


def oa_base(figure: str) -> tuple[str, str]:
    """Return OpenAero's base for a figure string, and the simplified figure.

    Mirrors the base determination in updateSequence/makeSequence
    (js/main/14-figures.js, around lines 2030 and 2110).
    """
    figure = re.sub(r'"[^"]*"', "", figure)
    if re.fullmatch(r"[-'`~]*", figure):
        figure = re.sub(r"-(?=--)", "+", figure)
    else:
        figure = re.sub(r"-(?=-)", "+", figure)
    # parseSequence (js/main.js, "replace longforward by 3x forward"): every '+' is
    # then a long forward line, three '~'. Without this a turn written with line
    # extensions ("+++2j+++") keeps them in its base and has no figure (F1).
    figure = figure.replace("+", "~~~")
    base = re.sub(r"[^a-zA-Z\-]+", "", figure)
    if re.fullmatch(r"-?i?s-?", base):
        figure = re.sub(r"(\d*i?s)", r"iv\1", figure, count=1)
        base = re.sub(r"i?s", "iv", base, count=1)
    base = base.replace("tri", "#")
    base = re.sub(r"i?[fseul]", "", base).replace("#", "tri")
    if base == "-":
        base = ("-+" if re.match(r"^[^a-zA-Z0-9\-\+]*-", figure) else "+-")
    elif base != "" or re.match(r"^[^\[\(]*[0-9fseul]", figure):
        if not base.startswith("-"):
            base = "+" + base
        if not base.endswith("-"):
            base += "+"
    if re.match(r"^.j[^w]", base):
        base = re.sub(r"[^a-zA-Z0-9\-\+]+", "", figure)
        if not base.startswith("-"):
            base = "+" + base
        if not base.endswith("-"):
            base += "+"
    return base, figure


@dataclass
class DirectionState:
    """OpenAero's OA.direction, OA.attitude, OA.goRight and OA.goFront."""

    direction: int = 0
    attitude: float = 0
    go_right: bool = True
    go_front: bool = True
    update_axis_dir: bool = True
    first_figure: bool = True
    results: list[FigureDirection] = field(default_factory=list)

    # ---- js/main/02-members.js -------------------------------------------------
    def change_dir(self, value: float) -> None:
        """changeDir"""
        self.direction = (((self.direction + value) % 360) + 360) % 360

    def change_att(self, value: float) -> None:
        """changeAtt, including the goRight update."""
        self.attitude = (((self.attitude + value) % 360) + 360) % 360
        if self.update_axis_dir:
            if (self.direction % 180) == 0 and value != 0:
                self.go_right = not (self.direction == 0)
                if 90 < self.attitude < 270:
                    self.go_right = not self.go_right
                elif self.attitude in (90, 270):
                    if (self.attitude == 90) == (value < 0):
                        self.go_right = not self.go_right
        else:
            self.update_axis_dir = True

    # ---- js/main/14-figures.js, sequence level ---------------------------------
    def entry_command(self, command: str) -> None:
        """The eu / ed / ej / eja entry 'figures' (around line 2058)."""
        self.attitude = 0
        if command == "eja":
            self.direction = 90
        elif command == "ej":
            self.direction = 270
        elif command == "ed":
            self.direction = 180
            self.go_right = False
        elif command == "eu":
            self.direction = 0
            self.go_right = True
        self.first_figure = True

    def subsequence(self) -> None:
        """The // token (around line 2043)."""
        self.first_figure = True
        if self.attitude == 180:
            self.attitude = 0
            self.change_dir(180)

    def apply(self, ofig) -> FigureDirection:
        """Process the drawing commands and the figure of an OlanFig."""
        for command in ofig.draw:
            if command in ("eu", "ed", "ej", "eja"):
                self.entry_command(command)
            elif command == "//":
                self.subsequence()
        return self.figure(ofig.token)

    def figure(self, token: str) -> FigureDirection:
        """Process one figure token and return its direction summary."""
        base, figure = oa_base(token)
        candidates = _figure_table().get(base)

        # autocorrect the entry attitude after the first (sub)figure (~line 2170).
        # first_figure is set at the start, after "//" and after an entry command
        # (eu, ed, ej, eja), as OpenAero's firstFigure || subSequence, so only a join
        # between two figures counts as a conflict.
        conflict = None
        if not self.first_figure:
            if (self.attitude == 0 and base[0] == "-") or (
                self.attitude == 180 and base[0] == "+"
            ):
                conflict = int(self.attitude)
                self.attitude = 180 - self.attitude
                self.change_dir(180)
        if candidates is None:
            # OpenAero draws an illegal figure (buildIllegal), after the autocorrect
            # and without building it, so firstFigure stays as it was
            res = FigureDirection(
                self.direction, self.attitude, self.direction, self.attitude, False, token
            )
            res.entry_conflict = conflict
            self.results.append(res)
            return res
        # the first figure starts inverted with the same drawing direction (~2186)
        if self.first_figure and base[0] == "-":
            self.attitude = 180
            self.change_dir(-180)
        # reset goRight for every figure that starts on the X axis (~2189)
        if self.direction % 180 == 0:
            self.go_right = (self.direction == 180) == (self.attitude == 0)
        res = self._build(candidates, base, figure, token)
        res.entry_conflict = conflict
        self.results.append(res)
        self.first_figure = False
        return res

    # ---- js/main/14-figures.js, buildFigure ------------------------------------
    def _build(
        self, candidates: list[list[str]], base: str, figure: str, token: str
    ) -> FigureDirection:
        entry_dir, entry_att = self.direction, self.attitude
        # goFront is true for every figure that does not start to the front (~25)
        self.go_front = not (
            (self.direction == 90 and self.attitude == 0)
            or (self.direction == 270 and self.attitude == 180)
        )

        patterns = [c[0] for c in candidates]
        fig_rolls = [_fig_rolls(pt, base) for pt in patterns]
        bare = re.sub(r"[+-]+", "", base)
        split = figure.split(bare) if bare else [figure]

        # the roll patterns: before the base, in brackets, and after (~line 60)
        nslots = len(fig_rolls[0])
        slots = [""] * nslots
        strip = re.compile(r"[+<~^>]")
        slots[0] = strip.sub("", split[0])
        if len(split) > 1:
            for k, r in enumerate(strip.sub("", split[1]).split(")")):
                if "(" in r:
                    if k + 1 < nslots:
                        slots[k + 1] = r.replace("(", "")
                else:
                    slots[nslots - 1] = r
        parsed = [parse_rolls(s) for s in slots]
        roll = [pr[0] for pr in parsed]
        roll_sums = [pr[1] for pr in parsed]

        # choose the figure variant that needs the least roll correction (~380)
        fig_idx = 0
        if len(candidates) > 1:
            best = math.inf
            for n, types in enumerate(fig_rolls):
                corr = 0.0
                for i, _r in enumerate(roll):
                    t = types[i] if i < len(types) else None
                    if t == 2:
                        corr += abs(_js_mod(roll_sums[i] + 180, 360))
                    elif t not in (3, 4):
                        corr += abs(_js_mod(roll_sums[i], 360))
                        if roll[i] and t == 9:
                            corr += 360
                if corr < best:
                    best = corr
                    fig_idx = n
        pattern, draw = candidates[fig_idx]
        types = fig_rolls[fig_idx]
        # rolls of type 9 (free length lines) are not rolls at all
        for i, t in enumerate(types):
            if t == 9 and i < len(roll):
                roll[i] = []
                roll_sums[i] = 0

        rollnr = 0 if _ROLL_BEFORE_BASE.match(pattern) else 1
        ctx = _FigureContext(figure, pattern, draw, roll, roll_sums, types)
        # buildFigure, "assign Aresti Nr and K Factor": the chosen variant's K
        k_variants = _k_table()["bases"].get(base)
        if k_variants is not None and k_variants[fig_idx][0] == pattern:
            _, aresti, k_powered, k_glider = k_variants[fig_idx]
            ctx.aresti.append(aresti)
            ctx.k_powered += k_powered
            ctx.k_glider += _glider_k(k_powered, k_glider)
        else:
            ctx.k_known = False
        ctx.neg_load = 1 if 90 < self.attitude < 270 else 0
        if "j" in draw.lower():
            if "_" in draw:
                # jw: the rolls' K come from the plain walk (it skips the turn);
                # the direction from the turn walk, on the state as it was
                saved = (self.direction, self.attitude, self.go_right, self.go_front, self.update_axis_dir)
                self._walk(ctx, rollnr)
                self.direction, self.attitude, self.go_right, self.go_front, self.update_axis_dir = saved
                ctx.figure = figure
            self._walk_turns(ctx)
        else:
            self._walk(ctx, rollnr)
        # direction switchers that were not used are ignored
        return FigureDirection(
            entry_dir,
            int(entry_att),
            int(self.direction),
            int(self.attitude),
            True,
            token,
            ctx.switch_x,
            ctx.switch_y,
            ctx.aresti,
            ctx.k_powered if ctx.k_known else None,
            ctx.k_glider if ctx.k_known else None,
            list(types),
            ctx.corrections,
        )

    def _walk(self, ctx: "_FigureContext", rollnr: int) -> None:
        draw = ctx.draw
        roll_top = False
        roll_top_after = 0.0
        i = 0
        while i < len(draw):
            c = draw[i]
            nxt = draw[i + 1] if i + 1 < len(draw) else ""
            if c in "'~" and self.attitude not in (90, 270):
                # buildFigure: a line sets the load from the attitude
                ctx.neg_load = 1 if 90 < self.attitude < 270 else 0
            if c in "jJ":
                # a turn inside a figure with rolls (jw): makeTurn
                m = re.match(r"[jJ][ioIO\d]+", draw[i:])
                if m:
                    self._make_turn(m.group(0))
                    i += len(m.group(0))
                    continue
            if c in "hH":
                # makeHammer (js/main/03-base-shapes.js)
                self.attitude = 270
                self.change_dir(180)
                ctx.neg_load = 0
                ctx.low_k_flick = True
            elif c in "tT":
                # makeTailslide
                self.attitude = 270
                ctx.low_k_flick = True
            elif c in "uU":
                # makePointTip
                self.change_att(180)
                self.change_dir(180)
            elif c == "_":
                rollnr, roll_top, roll_top_after = self._roll(
                    ctx, i, rollnr, roll_top, roll_top_after
                )
            elif c == "4":
                # clovers: fixed 1/4 roll
                ctx.figure = self._check_q_roll_switch(ctx, 90, i, rollnr)
            elif c in DRAW_ANGLES:
                angle = DRAW_ANGLES[c]
                if abs(angle) < 180 and nxt != "=":
                    self.change_att(angle)  # makeCorner
                else:
                    roll_top = nxt == "!"
                    if abs(angle) < 360 and not roll_top:
                        self.change_att(angle)
                    elif roll_top:
                        att_top = self.attitude + angle / 2
                        diff = (att_top / 180 - _js_int((att_top + 90) / 180)) * 180
                        if abs(diff) > 90:
                            diff = (att_top / 180 - _js_int((att_top - 90) / 180)) * 180
                        angle_top = angle / 2 - diff
                        top_line = 45 if angle_top > 0 else -45
                        self.change_att(angle_top - top_line)
                        self.change_att(top_line)
                        roll_top_after = angle - angle_top
                    else:
                        self.change_att(angle)  # full loops, drawn in parts
                # after every curve (buildFigure)
                ctx.neg_load = 1 if angle < 0 else 0
                ctx.low_k_flick = False
            i += 1

    def _roll(
        self,
        ctx: "_FigureContext",
        i: int,
        rollnr: int,
        roll_top: bool,
        roll_top_after: float,
    ) -> tuple[int, bool, float]:
        """The roll position '_' of the drawing string (~line 870 to 1160)."""
        if rollnr < len(ctx.roll):
            att_changed = 0
            roll_sum = 0
            for r in ctx.roll[rollnr]:
                self._roll_k(ctx, r, roll_sum)
                ctx.low_k_flick = True
                roll_sum += r.extent
                if (roll_sum + 180) % 360 == 0:
                    self.attitude = 180 - self.attitude
                    if self.attitude < 0:
                        self.attitude += 360
                    self.change_dir(abs(roll_sum))
                    roll_sum = 0
                    att_changed = 180 - att_changed
                    if roll_top:
                        ctx.neg_load = 1 - ctx.neg_load
                if self.attitude not in (90, 270) and not roll_top:
                    ctx.neg_load = 1 if 90 < self.attitude < 270 else 0
            ctx.low_k_flick = False
            roll_sum = ctx.roll_sums[rollnr]
            kind = ctx.types[rollnr] if rollnr < len(ctx.types) else 0
            correction = 0
            if kind == 1:
                correction = -_js_mod(roll_sum, 360)
                if att_changed == 180:
                    self.attitude = 180 - self.attitude
                    if self.attitude < 0:
                        self.attitude += 360
                    self.change_dir(180)
            elif kind == 2:
                # half rolls change direction and attitude
                correction = -_js_mod(roll_sum + 180, 360)
                if att_changed == 0:
                    self.attitude = 180 - self.attitude
                    if self.attitude < 0:
                        self.attitude += 360
                    self.change_dir(180)
            if correction:
                ctx.corrections.append((rollnr, int(correction)))
                # the correction roll OpenAero inserts has its own K
                code = {90: "4", 180: "2", 270: "3"}.get(abs(int(correction)))
                prefix = ROLL_ATTITUDES.get(int(self.attitude) % 360)
                if code and prefix is not None:
                    self._add_roll_k(ctx, prefix + code)
            if roll_top:
                if kind == 2:
                    roll_top_after = -roll_top_after
                top_line = 45 if roll_top_after > 0 else -45
                self.change_att(top_line)
                self.change_att(roll_top_after - top_line)
            else:
                ctx.figure = self._check_q_roll_switch(ctx, roll_sum, i, rollnr)
        return rollnr + 1, False, roll_top_after

    def _roll_k(self, ctx: "_FigureContext", r: _Roll, roll_sum: float) -> None:
        """The roll's aresti number and K (buildFigure, "Find which roll in
        figures.js matches"). roll_sum is the roll on this line before r."""
        att = int(round(self.attitude)) % 360
        prefix = ROLL_ATTITUDES.get(att)
        if prefix is None or not r.pattern:
            return
        if r.kind in ("possnap", "negsnap"):
            vertical = att in (90, 270)
            if vertical and ctx.low_k_flick:
                load = "+" if r.kind == "possnap" else "-"
            elif _js_mod(roll_sum, 180) == 0 or vertical:
                load = "+" if ctx.neg_load == 0 else "-"
            else:
                # snaps from knife edge: the load the previous roll implies
                inv = 90 < att < 270
                inv = inv == (_js_mod(abs(roll_sum) - 90, 360) == 0)
                inv = inv == (roll_sum * r.extent > 0)
                load = "+" if inv else "-"
            prefix = load + prefix
        self._add_roll_k(ctx, prefix + r.pattern)

    @staticmethod
    def _add_roll_k(ctx: "_FigureContext", key: str) -> None:
        entry = _k_table()["rolls"].get(key)
        if entry is None:
            return  # a non-Aresti roll has no K
        aresti, k_powered, k_glider = entry
        ctx.aresti.append(aresti)
        ctx.k_powered += k_powered
        ctx.k_glider += _glider_k(k_powered, k_glider)

    def _check_q_roll_switch(
        self, ctx: "_FigureContext", roll_sum: float, fd_index: int, rollnr: int
    ) -> str:
        """checkQRollSwitch (js/main/14-figures.js, ~line 1468)."""
        if not (self.attitude in (90, 270) and _js_mod(roll_sum, 180)):
            return ctx.figure
        draw, roll, figure = ctx.draw, ctx.roll, ctx.figure
        self.change_dir(abs(roll_sum))
        next_angle = 0
        next_extent = 0
        next_extent_prev = 0
        switch_vert = False
        vertical_rolls = len(re.findall(r"[&$]", ctx.pattern))
        first_roll = rollnr == 0
        k = rollnr
        for i in range(fd_index + 1, len(draw)):
            ch = draw[i]
            if ch in DRAW_ANGLES:
                next_angle = DRAW_ANGLES[ch]
                if _js_mod(next_angle, 180):
                    break
            elif ch == "_":
                k += 1
                next_extent_prev = next_extent
                if k < len(roll):
                    for r in roll[k]:
                        next_extent += r.extent
                if _js_mod(next_extent, 180):
                    if vertical_rolls > 2 and first_roll:
                        if k == 2:
                            next_extent = next_extent_prev
                            break
                        # a first part direction switcher (;> or ;^) before the base
                        letters = re.search(r"[a-zA-Z]+", ctx.pattern).group(0)
                        rx = re.compile(r";[>^]" + letters)
                        switch_dir = bool(rx.search(figure))
                        if switch_dir:
                            figure = rx.sub("$1", figure, count=1)
                        if self.direction % 180 == 0:
                            if (
                                (((self.attitude == 90) == (self.direction == 0))
                                 == (next_angle > 0)) == self.go_right
                            ) != switch_dir:
                                self.change_dir(180)
                            self.go_front = not self.go_front
                        else:
                            if (
                                (((self.attitude == 90) == (self.direction == 270))
                                 == (next_angle > 0)) == self.go_front
                            ) != switch_dir:
                                self.change_dir(180)
                            if self.update_axis_dir:
                                self.go_front = not self.go_front
                        self.update_axis_dir = False
                        return figure
                    break
                else:
                    switch_vert = not switch_vert
            elif ch == "h":
                next_extent += 180  # virtual roll for hammerheads
        if self.direction % 180 == 0:
            if abs(next_angle) > 180:
                next_angle = -next_angle
            if (
                (((self.attitude == 90) == (self.direction == 0)) == (next_angle > 0))
                == self.go_right
            ) != switch_vert:
                self.change_dir(180)
            if ">" in figure:
                self.change_dir(180)
                ctx.switch_x = True
                if next_extent == 0:
                    figure = figure.replace(">", "", 1)
            else:
                ctx.switch_x = False
            # just changed from Y to X axis; the next X to Y goes the other way
            if self.update_axis_dir:
                self.go_front = not self.go_front
        else:
            if abs(next_angle) > 180:
                next_angle = -next_angle
            if (
                (((self.attitude == 90) == (self.direction == 90)) == (next_angle < 0))
                == self.go_front
            ) != switch_vert:
                self.change_dir(180)
            if "^" in figure:
                self.change_dir(180)
                ctx.switch_y = True
                if next_extent == 0:
                    figure = figure.replace("^", "", 1)
            else:
                ctx.switch_y = False
        if not _js_mod(next_extent, 180):
            self.change_dir(-next_extent)
        return figure

    def _walk_turns(self, ctx: "_FigureContext") -> None:
        """(Rolling) turns: the 'j' case of buildFigure and makeTurn (02-members.js)."""
        figure = ctx.figure
        prefix = ""
        if re.search(r"[>^]", figure):
            ctx.switch_x = True
            prefix = ">"
        else:
            ctx.switch_x = False
        second_turn = False
        for match in re.findall(r"[jJ][ioIO\d]+", ctx.draw):
            if second_turn and re.match(r"[jJ][ioIO]*1", match):
                prefix = ">"
            self._make_turn(prefix + re.sub(r"[^jioJIO\d]+", "", match))
            second_turn = True

    def _make_turn(self, draw: str) -> None:
        """makeTurn (js/main/02-members.js, ~line 1030)."""
        sign = 1
        numbers = re.sub(r"[^\d]+", "", draw)
        extent = int(numbers[0]) * 90
        if extent in (90, 270):
            self.change_dir(sign * extent)
            if self.direction % 180 == 0:
                if (((self.direction == 0) == (self.attitude == 0)) != self.go_right):
                    sign = -sign
            else:
                if (self.direction == 90) == (self.attitude == 0):
                    sign = -sign
            self.change_dir(-extent)
        else:
            if self.direction % 180 == 0:
                if (self.direction == 0) == (self.attitude < 180):
                    sign = -sign
            else:
                if (((self.direction == 90) == (self.attitude == 0)) != self.go_right):
                    sign = -sign
        if draw[0] == ">":
            sign = -sign
        new_attitude = (360 - self.attitude) % 360 if extent == 180 else self.attitude
        if len(numbers) > 1:
            for r in numbers[1:]:
                if r == "5":
                    self.change_dir(180)
                    self.change_att(180)
            self.change_dir(sign * extent)
        elif extent != 360:
            self.change_dir(sign * extent)
            self.attitude = new_attitude
        else:
            self.change_dir(180)
            self.change_dir(180)


@dataclass
class _FigureContext:
    figure: str
    pattern: str
    draw: str
    roll: list[list[_Roll]]
    roll_sums: list[int]
    types: list[int]
    switch_x: bool = False
    switch_y: bool = False
    aresti: list[str] = field(default_factory=list)
    k_powered: int = 0
    k_glider: int = 0
    k_known: bool = True
    neg_load: int = 0  # OA.negLoad
    low_k_flick: bool = False  # buildFigure's lowKFlick
    corrections: list[tuple[int, int]] = field(default_factory=list)


def walk_olan(tokens: list[str]) -> list[FigureDirection]:
    """Run OpenAero's direction state over OLAN tokens (a split sequence).

    Used by the tests; parse_olan calls the state itself so it can interleave
    its own figure parsing.
    """
    from .errors import NoFigureLeft
    from .figure_parser import OlanFig

    state = DirectionState()
    rest = list(tokens)
    out: list[FigureDirection] = []
    while rest:
        try:
            ofig, rest = OlanFig.take(rest)
        except NoFigureLeft:
            break
        out.append(state.apply(ofig))
    return out
