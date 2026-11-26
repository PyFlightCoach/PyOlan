"""This module handles an entire olan figure.

An instance of OlanFig contains all the information relating to a figure from an olan string. 
This includes the original string and the important parts of it, the OFig primitive and all the
information on the rolls.

The OlanFig.take constructor will read the next figure from an olan array (an olan sequence split on 
spaces) return the OlanFig instance and the remaining olan array.

The create_elements method will create the pyflightcoach principal elements for the figure.
"""

from __future__ import annotations
import re
import json
import itertools
from dataclasses import dataclass, field, replace
from functools import lru_cache
from importlib.resources import files
from typing import Tuple


import numpy as np
import schemas.positioning as p
from loguru import logger
from schemas import aresti as a, ManInfo

from .primitives import OFig, li, lo, tu, ofig_re, olan_figs
from .rolls import OlanRoll, ro
from .drawn import FIXED_QUARTER, elements_from_draw
from .sizing import SizeGroups, Sizing, size_groups

from .drawing import re_drawing, re_draw, strip_comments
from .errors import NoFigureLeft, OlanParseError


_OLAN_CHARACTERS = re.compile(r"[0-9a-zA-Z_&$;,()\-+~`'.>^/%\[\]\"|]")


# Phase S, SQ5 (user, 2026-11-26): OpenAero's non-Aresti figures (its Family 0, the
# catalogue numbers 0.x) raise under every rule set, the point tip ("th", D11) among
# them. The message lists them all, so a pilot sees that it is a short list.
NON_ARESTI_FIGURES = (
    "the wingover (jw)",
    "the clover leaves (oj, ioj)",
    "the half loops with a quarter roll (mj, aj)",
    "the 360 degree rolling turns with a half roll (4j5, 4jo5)",
    "the tip-head hammer (th)",
    "the extended vertical line figures (vv, hat)",
    "the hammer P-loops (hp, iph, ibh, ipbh)",
    "the triangle (tri)",
    "the extended Immelmann and split S (xm, xa)",
    "the loop with turns (oaj)",
)
NON_ARESTI = (
    "FCScore cannot analyse OpenAero's non-Aresti figures yet; we are working on it. "
    "They are the only figures it cannot analyse: "
    + ", ".join(NON_ARESTI_FIGURES[:-1])
    + f" and {NON_ARESTI_FIGURES[-1]}, upright or inverted. Every Aresti catalogue "
    "figure can be analysed."
)
# the point tip is one of them (D11); the name is kept for the OpenAero harness
POINT_TIP = NON_ARESTI


def non_aresti(aresti: list[str]) -> bool:
    """Whether OpenAero's catalogue number for the figure is a non-Aresti one (0.x)."""
    return bool(aresti) and aresti[0].split(".")[0] == "0"


def _unreadable(token: str) -> str:
    """Why a token is neither a figure nor a drawing command, for a pilot."""
    bad = [c for c in strip_comments(token) if not _OLAN_CHARACTERS.fullmatch(c)]
    if bad:
        return f'"{bad[0]}" is not an OLAN character'
    letters = re.sub(r"[^a-zA-Z]", " ", re_draw.sub("", strip_comments(token))).split()
    if letters:
        return f'"{letters[0]}" is not an OLAN figure or roll that PyOlan can build'
    return "not an OLAN figure, roll or drawing command"


def _with_roll(roll: OlanRoll | None, degrees: int) -> OlanRoll:
    """roll with a correction roll of degrees added after the rolls written."""
    arr = list(roll.roll_arr) if roll else []
    piece = max((r.piece for r in arr), default=-1) + 1
    added = replace(ro(degrees / 360), piece=piece)
    return OlanRoll(roll.rawroll if roll else "", arr + [added])


def horizontal_fractions(start: float, amount: float, tol: float = 1e-9) -> list[float]:
    """Fractions of a loop at which the flight path is horizontal.

    start is the path angle at the start of the loop and amount the signed
    geometric change in path angle over it, both in turns. The path is
    horizontal where the angle is a multiple of 1/2 (the apex of an upright or
    inverted loop and the nadir of one). Only interior points count: a loop that
    starts or ends level has no apex to centre a roll on.
    """
    if abs(amount) < tol:
        return []
    low, high = sorted((start, start + amount))
    found = []
    for k in range(int(np.floor(low * 2)) - 1, int(np.ceil(high * 2)) + 2):
        fraction = (k / 2 - start) / amount
        if tol < fraction < 1 - tol:
            found.append(float(fraction))
    return found


@dataclass
class OlanFig:
    draw: list[str]
    rawfig: str
    fig: OFig
    inverted: bool
    prefix: OlanRoll | None
    suffix: list[OlanRoll]
    final: OlanRoll | None
    entry: p.Orientation
    exit: p.Orientation
    entry_direction: p.Direction = p.Direction.UPWIND
    source_pattern: str = ""
    token: str = ""  ## the whole OLAN token, including drawing characters
    warnings: list[str] = field(default_factory=list)  # for the pilot (D1)
    # When the elements come from OpenAero's drawing string (drawn.py): the OpenAero
    # roll slot each element holds (None for none), and the number of slots. The loop
    # signs are then the ones drawn, and the rolls go by slot. None for a figure that
    # keeps its hand-written primitive.
    drawn_slots: list[int | None] | None = None
    drawn_nslots: int = 0

    def __len__(self):
        return len(self.fig.oels)

    def openaero(self):
        """OpenAero's reading of this figure on its own (direction.py): the variant,
        its aresti numbers and K."""
        from .direction import DirectionState

        return DirectionState().figure(self.token)

    def k_factor(self, glider: bool = False) -> int:
        """OpenAero's K for this figure: the catalogue K of the variant OpenAero
        chooses plus the K of each roll, from the aresti numbers (D8). Rule-specific
        K (OpenAero's kRules) is not applied. Raises OlanParseError when OpenAero
        has no figure for it."""
        d = self.openaero()
        k = d.k_glider if glider else d.k_powered
        if k is None:
            raise OlanParseError(
                "OpenAero has no catalogue figure for it (check the entry and exit "
                "attitude markers and the rolls), so it has no K",
                self.token,
            )
        return k

    @property
    def k_powered(self) -> int:
        return self.k_factor()

    @property
    def k_glider(self) -> int:
        return self.k_factor(glider=True)

    @staticmethod
    def take(data: list[str]) -> Tuple[OlanFig, list[str]]:
        """read one olan figure from an array of strings, return figure and the remaining array

        Raises NoFigureLeft when only drawing commands are left, and OlanParseError
        (with the token and its index in data) for an item that is neither a drawing
        command nor a figure.
        """
        draw = []
        for i, d in enumerate(data):
            if re_drawing.match(d):
                draw.append(d)
                continue
            bad = [c for c in strip_comments(d) if not _OLAN_CHARACTERS.fullmatch(c)]
            if bad:
                raise OlanParseError(f'"{bad[0]}" is not an OLAN character', d, i)
            try:
                found = OlanFig._read_token(d)
            except OlanParseError as ex:
                raise ex.at(token=d, index=i) from None
            if found is None:
                raise OlanParseError(_unreadable(d), d, i)
            rawfig, fig_chars, ofig, _prefix, _suffix = found
            break
        else:
            raise NoFigureLeft("No olan figure found in data")
        try:
            return OlanFig._build(d, draw, rawfig, fig_chars, ofig, _prefix, _suffix), data[i + 1 :]
        except OlanParseError as ex:
            raise ex.at(token=d, index=i) from None
        except (ValueError, KeyError, IndexError) as ex:
            raise OlanParseError(f"cannot be read ({ex})", d, i) from ex

    @staticmethod
    def _read_token(d: str):
        """(rawfig, fig_chars, ofig, prefix, suffix) for a figure token, else None."""
        rawfig = re_draw.sub("", d)
        fig_chars = None

        # check if it is a figure
        res = ofig_re.search(strip_comments(d))
        if res and res.group(2):
            fig_chars = res.group(2)
            ofig = olan_figs[res.group(2).lstrip("i")]
            if res.group(2).startswith("i") and not ofig.invertable:
                ofig = olan_figs[res.group(2)]
        if not fig_chars:
            # check if it is a spin
            res = re.search(r"([^a-z]|^)(s|is)([^a-z]|$)", strip_comments(rawfig))
            if res and res.group(2):
                # A spin with no figure ("s", "6s", "+5s", "-5is", "6s-") is
                # OpenAero's iv downline with that spin on it: makeSequence writes
                # "iv" before the spin (F7). Built that way the downline can swap
                # the exit direction, as for any spin on a vertical line (F24). The
                # figure keeps its name.
                rawfig = re.sub(r"(\d*i?s)", r"iv\1", strip_comments(rawfig), count=1)
                fig_chars = "iv"
                ofig = replace(olan_figs["v"], name="Spin", short_name="sp")

        if fig_chars:
            # the rolls are read without comments; rawfig keeps them, as before
            _prefix, _suffix = strip_comments(rawfig).split(fig_chars, 1)
            return rawfig, fig_chars, ofig, _prefix, _suffix

        # A line with attitude markers and nothing else is OpenAero's horizontal
        # line figure (F21): "--" level inverted (1.1.1.2), and a single "-" an
        # inverted entry to an upright exit (1.1.1.4), the half roll it needs being
        # OpenAero's correction roll. OpenAero reads "+" as a long line and the rest
        # as line lengths (oa_base).
        bare = strip_comments(rawfig)
        if "-" in bare and re.fullmatch(r"[-~+`'.]+", bare):
            from .direction import oa_base

            base = oa_base(bare)[0]
            if base in ("-+", "--"):
                return base, "r", OFig("Roll", "roll", "r", [li()]), "", ""

        # check if it is a roll. A roll figure may carry attitude markers: "-" before
        # it for an inverted entry, "-" after it for an inverted exit ("24-",
        # "-,2", "-22--"; OpenAero reads the extra "-" as line extensions).
        bare = strip_comments(rawfig)
        core = re.sub(r"-+$", "", re.sub(r"^-", "", bare))
        if core and not re.search(r"[a-eg-hj-rt-zA-Z]", core):
            roll = OlanRoll.parse(core)
            if roll and len(roll.roll_arr):
                ofig = OFig("Roll", "roll", "r", [li()])
                entry = "-" if bare.startswith("-") else ""
                exit_ = "-" if bare.endswith("-") and len(bare) > 1 else ""
                return entry + core + exit_, "r", ofig, "", core
        return None

    @staticmethod
    def _build(d, draw, rawfig, fig_chars, ofig, _prefix, _suffix) -> OlanFig:
        # Special handling for rolling circles
        if fig_chars in ("j", "ji", "jo", "jio", "joi"):
            ofig = OFig(
                "turn",
                "turn",
                fig_chars,
                [tu(fig_chars.split("j")[1] or "i", int(_prefix.strip("-") or 1) / 4)],
            )
            prefix = None
            suffix = []

            # The digits after j are rolls, one digit at a time as OpenAero reads
            # them (makeTurn): "5" is a half roll, any other digit that many full
            # rolls ("15": a roll then a half roll). The first roll goes inwards
            # for j, ji and jio and outwards for jo and joi; jio and joi alternate
            # every roll. Consecutive rolls the same way are one roll (F17).
            digits = _suffix.strip("-")
            if not re.fullmatch(r"\d*", digits):
                raise OlanParseError(f'"{digits}" is not a rolling turn roll count')
            sign = 1 if ofig.chars in ["j", "ji", "jio"] else -1
            alternate = ofig.chars in ["joi", "jio"]
            suff_rolls = []
            for digit in digits:
                for amount in [0.5] if digit == "5" else [1] * int(digit):
                    if suff_rolls and not alternate and np.sign(suff_rolls[-1].turns) == sign:
                        suff_rolls[-1] = ro(suff_rolls[-1].turns + sign * amount)
                    else:
                        suff_rolls.append(ro(sign * amount))
                    if alternate:
                        sign = -sign
            final = OlanRoll(_suffix, suff_rolls) if suff_rolls else None

        else:
            prefix = OlanRoll.parse(_prefix.lstrip("-").split(")")[-1])
            suffix = [OlanRoll.parse(r) for r in re.findall(r"\((.*?)\)", _suffix)]
            final = OlanRoll.parse(_suffix.split(")")[-1].rstrip("-"))

        entry_direction = p.Direction.UPWIND
        for dr in draw:
            if dr in ["ej", "eja"]:
                entry_direction = p.Direction.CROSS
            elif dr == "ed":
                entry_direction = p.Direction.DOWNWIND
            elif dr == "eu":
                entry_direction = p.Direction.UPWIND

        return OlanFig(
            draw,
            rawfig,
            ofig,
            fig_chars.startswith("i") and ofig.invertable,
            prefix,
            suffix,
            final,
            p.Orientation.INVERTED if rawfig.startswith("-") else p.Orientation.UPRIGHT,
            p.Orientation.INVERTED if rawfig.endswith("-") else p.Orientation.UPRIGHT,
            entry_direction,
            d if d.startswith(("-", "+")) else "",
            d,
        )._with_corrections()._drawn()

    def _drawn(self) -> OlanFig:
        """Take the elements from the drawing string of the variant OpenAero
        chooses (drawn.py), where it can be drawn. Raises OlanParseError for a
        figure OpenAero has no figure for (D10, plan step 5) and for a point tip
        (D11)."""
        if self.fig.chars in self.TURN_CHARS:
            return self
        oa = self.openaero()
        if not oa.resolved:
            raise OlanParseError(self._not_openaero())
        if self.fig.chars == "r" or not oa.draw:
            return self
        drawn = elements_from_draw(oa.draw)
        if drawn is None:
            return self
        oels, slots = drawn
        self.fig = replace(self.fig, oels=oels, turnable=None)
        self.drawn_slots = [s if s is None or isinstance(s, str) else oa.first_slot + s for s in slots]
        self.drawn_nslots = len(oa.roll_slots)
        # the attitude OpenAero exits in, which the drawn elements fly; it can differ
        # from the written exit marker when the rolls written leave the other way
        if oa.exit_attitude in (0, 180):
            self.exit = p.Orientation.INVERTED if oa.exit_attitude == 180 else p.Orientation.UPRIGHT
        # OpenAero ignores a roll written where the figure has no roll ("o(2)": a
        # loop has no roll in brackets); so does PyOlan, but it says so (D7)
        used = {s for s in self.drawn_slots if isinstance(s, int)}
        n = self.drawn_nslots
        written = [(0, self.prefix, "before the figure")]
        # the bracketed slots are 1 to n - 2; a bracket beyond them has no slot
        written += [
            (k + 1 if k + 1 < n - 1 else None, r, "in brackets") for k, r in enumerate(self.suffix)
        ]
        written += [(n - 1, self.final, "after the figure")]
        for slot, roll, where in written:
            if roll is not None and roll.roll_arr and slot not in used:
                self.warnings.append(
                    f'OpenAero ignores the roll "{roll.rawroll}" written {where}: the '
                    "figure has no roll there, so it is built without it"
                )
        return self

    def _not_openaero(self) -> str:
        """Why OpenAero has no figure for this one, for a pilot."""
        from .direction import _figure_table

        code = re.sub(r"[^a-z]", "", strip_comments(self.rawfig))
        code = re.sub(r"^(if|f|is|s)(?=[a-z])|(?<=[a-z])(if|f|is|s)$", "", code)
        letters = self.fig.chars.split("|")
        written = next((c for c in letters + [f"i{c}" for c in letters] if c == code), code)
        if not any(f"{a}{written}{b}" in _figure_table() for a in "+-" for b in "+-"):
            return (
                f'"{written}" is not an OpenAero figure (it was a PyOlan code for '
                f"{self.fig.name.lower()}), so it cannot be read"
            )
        return (
            "OpenAero has no figure like this. Check the attitude markers: a figure "
            'that starts or ends inverted needs a "-" before or after it'
        )

    def _slot_roll(self, slot: int) -> OlanRoll | None:
        """The roll written for an OpenAero roll slot: the roll before the base, the
        rolls in brackets, the roll after (as _with_corrections places them)."""
        n = self.drawn_nslots
        if n == 1 or slot == n - 1:
            return self.final
        if slot == 0:
            return self.prefix
        return self.suffix[slot - 1] if slot - 1 < len(self.suffix) else None

    ROLL_WORDS = {90: "a quarter roll", 180: "a half roll", 270: "a three quarter roll"}

    def _with_corrections(self) -> OlanFig:
        """Insert the rolls OpenAero inserts where the OLAN leaves out a roll the
        figure needs (D1), and say so in warnings.

        OpenAero's roll slots are, in order, the roll before the base, the rolls in
        brackets and the roll after (a roll-only figure has one): PyOlan's prefix,
        suffix and final. The roll goes after the rolls written in that slot.
        """
        if non_aresti(self.openaero().aresti):
            raise OlanParseError(NON_ARESTI)
        if self.fig.chars in self.TURN_CHARS:
            if not self.openaero().resolved:
                # OpenAero rejects it, e.g. 3jio15 written with an upright exit (F19)
                raise OlanParseError(
                    "OpenAero has no turn or rolling turn like this. Check the attitude "
                    'markers: rolls that end inverted need a "-" after the figure'
                )
            return self
        oa = self.openaero()
        if not oa.corrections:
            return self
        n = len(oa.roll_slots)
        for slot, degrees in oa.corrections:
            if n == 1 or slot == n - 1:
                self.final = _with_roll(self.final, degrees)
            elif slot == 0:
                self.prefix = _with_roll(self.prefix, degrees)
            else:
                suffix = list(self.suffix) + [None] * (slot - len(self.suffix))
                suffix[slot - 1] = _with_roll(suffix[slot - 1], degrees)
                self.suffix = suffix
            self.warnings.append(
                f"OpenAero adds {self.ROLL_WORDS.get(abs(degrees), f'a {abs(degrees)} degree roll')} "
                "that the OLAN leaves out; the figure is built with it"
            )
        return self

    def create_info(self):
        return ManInfo.build(
            "olan figure",
            "ofig",
            10,
            p.BoxLocation(
                height=p.Height.MID,
                direction=p.Direction.UPWIND,
                orientation=self.entry,
            ),
            p.BoxLocation(height=p.Height.MID),
        )

    TURN_CHARS = frozenset({"j", "ji", "jo", "jio", "joi"})
    # entry roll, loop KE and exit roll for a right-hand plain turn.
    TURN_BANK = (np.radians(60), np.radians(30), np.radians(-60))

    def turn_options(self) -> list[list[float]] | None:
        """Linked parameter options for a single turn, or None if not a turn.

        A turn can be flown either way, so two mirrored options are returned.
        Plain turns link the entry roll, loop KE and exit roll. Rolling turns link
        the turn angle and each roll angle; the mirrored option reverses all of
        them, so a roll keeps its direction relative to the turn (inwards or
        outwards, alternating for jio and joi; F4).
        """
        if self.fig.chars not in self.TURN_CHARS:
            return None
        if self.final:
            rolls = np.atleast_1d(self.final.angles()).astype(float)
            option = [self.fig.oels[0].turnamount * 2 * np.pi, *rolls]
        else:
            option = list(self.TURN_BANK)
        option = [float(v) for v in option]
        return [option, [-v for v in option]]

    def element_rolls(self) -> list[OlanRoll | None]:
        if self.drawn_slots is not None:
            return [
                None if s is None
                else OlanRoll(FIXED_QUARTER, [ro(0.25)]) if s == FIXED_QUARTER
                else self._slot_roll(s)
                for s in self.drawn_slots
            ]
        # n==4: p fig (s0) (s1) f
        # n==3: p fig (s0) f
        # n==2: p fig f
        # n==1: fig f
        roll_positions = [i for i, el in enumerate(self.fig.oels) if el.canRoll]
        nrolls = len(roll_positions)
        rolls = [None for _ in self.fig.oels]

        def safe_get_item(arr: list, i: int):
            try:
                return arr[i]
            except IndexError:
                return None

        if nrolls == 1:
            # OpenAero accepts the roll in brackets too, e.g. o(2)
            rolls[roll_positions[0]] = self.final or safe_get_item(self.suffix, 0)
        elif nrolls == 2:
            rolls[roll_positions[0]] = self.prefix
            rolls[roll_positions[1]] = self.final
        elif nrolls == 3:
            rolls[roll_positions[0]] = self.prefix
            rolls[roll_positions[1]] = safe_get_item(self.suffix, 0)
            rolls[roll_positions[2]] = self.final
        elif nrolls == 4:
            rolls[roll_positions[0]] = self.prefix
            rolls[roll_positions[1]] = safe_get_item(self.suffix, 0)
            rolls[roll_positions[2]] = safe_get_item(self.suffix, 1)
            rolls[roll_positions[3]] = self.final
        return rolls

    def can_swap_exit(self) -> np.ndarray | bool:
        """Per element mask of direction-changing lines.

        A direction-changing line is a vertical line whose net roll, including a
        spin on that line, wraps to plus or minus 90 degrees. Flying that roll the
        other way exits the figure in the opposite direction.
        """
        if all([el.loopamount == 0 for el in self.fig.oels]):
            return False
        rolls = self.element_rolls()
        roll_totals = np.array([r.total() if r else 0 for r in rolls])

        loops = np.array([e.loopamount for e in self.fig.oels])

        if self.drawn_slots is not None:
            # the drawn loops are signed by the pull, so the path angle comes
            # from path_angles
            angles = self.path_angles(loops, rolls)[0][:-1]
            is_vertical = np.isclose(np.mod(angles, 0.5), 0.25)
        else:
            direction = np.concatenate((np.array([0]), (loops.cumsum() % 1)[:-1]))
            is_vertical = (direction == 0.25) | (direction == 0.75)
        is_line = np.array([e.kind == "Line" for e in self.fig.oels])

        return (
            is_vertical
            & is_line
            & np.isclose(np.abs(roll_totals) % 0.5, 0.25)
        )

    def direction_lines(self) -> list[int]:
        """Indices of the direction-changing lines (see can_swap_exit)."""
        return [int(i) for i in np.flatnonzero(self.can_swap_exit())]

    def _linked_roll_refs(self) -> tuple[dict[int, list[int]], int]:
        """Map each direction-changing line to its roll_option indices.

        Every roll point on the line, including a spin, gets one index.
        Returns the map and the total number of indices.
        """
        rolls = self.element_rolls()
        refs: dict[int, list[int]] = {}
        k = 0
        for i in self.direction_lines():
            n = len(rolls[i].roll_arr)
            refs[i] = list(range(k, k + n))
            k += n
        return refs, k

    def roll_option_vectors(self) -> list[list[float]]:
        """All sign combinations of the linked direction-changing line rolls.

        Each line takes one sign, applied to every roll point on it so the OLAN
        relative signs are preserved. The first line is positive (as written)
        in the first vectors.
        """
        rolls = self.element_rolls()
        lines = self.direction_lines()
        vectors = []
        for signs in itertools.product([1, -1], repeat=len(lines)):
            vec: list[float] = []
            for i, sign in zip(lines, signs):
                vec.extend(
                    (sign * np.atleast_1d(rolls[i].angles()).astype(float)).tolist()
                )
            vectors.append(vec)
        return vectors

    def loop_amounts(self, element_rolls: list[OlanRoll]) -> list[float]:
        if self.drawn_slots is not None:
            # drawn by OpenAero for the variant it chose: already signed by the pull
            return np.array([e.loopamount for e in self.fig.oels], dtype=float)
        if all([el.loopamount == 0 for el in self.fig.oels]):
            return np.zeros(len(self.fig.oels))

        def swap(test):
            """returns -1 for false and 1 for true"""
            return np.where(test, 1, -1)

        roll_totals = np.array([r.total() if r else 0 for r in element_rolls])

        loops = np.array([e.loopamount for e in self.fig.oels])

        direction = np.concatenate((np.array([0]), (loops.cumsum() % 1)[:-1]))
        is_vertical = (direction == 0.25) | (direction == 0.75)

        if self.inverted:
            # If figure is inverted loops before first vertical line are swapped,
            # all of them when it has no vertical line ("ic" is the c mirrored
            # top to bottom: a 5/8 loop down then 1/8 up to the exit line).
            last_swapped = is_vertical.argmax() if is_vertical.any() else len(self) - 1
            loops = loops * np.where(
                np.arange(len(self)) <= last_swapped,
                -1,
                1,
            )
            
            direction = np.concatenate((np.array([0]), (loops.cumsum() % 1)[:-1]))

        # If exit is inverted the loop before the first vertical line are swapped
        if sum(is_vertical) > 0:
            entry_swap = np.where(
                np.arange(len(self)) <= is_vertical.argmax(),
                swap(self.entry == p.Orientation.UPRIGHT),
                1,
            )
        else:
            entry_swap = np.ones(len(self)) * swap(self.entry == p.Orientation.UPRIGHT)

        # At half roll increments the directions of the following loops are
        # swapped; if the line is vertical the swap is cancelled. The swap starts
        # after the rolling element: a roll inside a loop (e.g. p(2)) does not
        # change the direction of that loop, which the builder flies with the roll.
        roll_swap = []
        is_swapped = 1
        for hrp, isvert in zip(np.where(roll_totals % 1 == 0.5, 0.5, 0), is_vertical):
            if isvert:
                is_swapped = 1
            roll_swap.append(is_swapped)
            if hrp == 0.5 and not isvert:
                is_swapped = -is_swapped

        loops = loops * entry_swap * np.array(roll_swap)

        if self.fig.turnable is not None:
            # reverse all elements after the turnable element to make
            # the exit attitude correct.

            turn_index = (
                self.fig.turnable
                if self.fig.turnable > 0
                else len(loops) + self.fig.turnable
            )

            # reverse all elements from the turnable element when the exit
            # attitude they give does not match the OLAN exit attitude.
            if self.exit_attitude(loops, element_rolls) != self.exit:
                loops = np.where(np.arange(len(loops)) >= turn_index, -loops, loops)

        return loops

    def path_angles(
        self, loops: np.ndarray, element_rolls: list[OlanRoll | None]
    ) -> tuple[np.ndarray, np.ndarray]:
        """The flight path angle and canopy side at the start of each element.

        loops are the signed loop amounts (pull positive) and element_rolls the
        rolls of each element, as returned by loop_amounts and element_rolls.
        Tracks the flight path angle in the plane of the figure, in turns, with 0
        along the entry heading and positive climbing, and which side of the path
        the canopy is on (1 up, -1 down). A loop follows its geometric path, so a
        half roll in a loop (or on a line) only moves the canopy to the other side.
        Quarter rolls change the plane but not the pull or push needed afterwards,
        so they are ignored here.

        Both arrays have one more item than there are elements: the last is the
        state after the final element. Within an element the path angle moves
        linearly by ``loops[i] * canopy[i]``, the canopy flipping after it.
        """
        angle = 0.0
        canopy = 1 if self.entry == p.Orientation.UPRIGHT else -1
        angles = [angle]
        canopies = [canopy]
        for amount, roll in zip(loops, element_rolls):
            angle += amount * canopy
            if roll is not None and roll.roll_arr and abs(roll.total()) % 1 == 0.5:
                canopy = -canopy
            angles.append(angle)
            canopies.append(canopy)
        return np.array(angles), np.array(canopies)

    def exit_attitude(
        self, loops: np.ndarray, element_rolls: list[OlanRoll | None]
    ) -> p.Orientation:
        """The exit attitude given signed loop amounts (pull positive)."""
        angles, canopies = self.path_angles(loops, element_rolls)
        # upright when the canopy points up: horizontal with canopy at +90 degrees
        up = (round(angles[-1] * 4) % 4 == 0) == (canopies[-1] > 0)
        return p.Orientation.UPRIGHT if up else p.Orientation.INVERTED

    def size_groups(self, sizing: Sizing | None) -> SizeGroups:
        """The loops and lines the rule set's sizing policy compares (sizing.py).

        Only a figure drawn from OpenAero's drawing string has groups: the rolling
        turns and the hand-written primitives have none."""
        if sizing is None or self.drawn_slots is None:
            return SizeGroups()
        return size_groups(
            self.fig.oels, self.openaero().aresti[0], sizing, self.element_rolls()
        )

    ROLL_ANGLE = np.radians(90)

    def _loop_roll_kwargs(
        self, roll: OlanRoll, start: float, amount: float
    ) -> dict[str, object]:
        """The roll arguments for a loop, centring the roll on its apex or nadir.

        The rules ask for a roll in a loop to be symmetric about the apex (or
        nadir), however much of the loop it uses. start is the path angle at the
        start of the loop and amount the geometric change in path angle over it,
        both in turns. A loop with one level point inside it has the roll
        centred on that point. One with none (the level point is at an end) has
        the roll spanning as much of the loop as it can.
        """
        kwargs: dict[str, object] = dict(
            rolls=roll.pfc_roll(),
            rolltypes=roll.rolltypes(),
            rollangle=self.ROLL_ANGLE,
        )
        points = horizontal_fractions(start, amount)
        if len(points) > 1:
            raise ValueError(
                f"loop of {amount} turns from path angle {start} is level at more "
                f"than one interior point ({points}), so the roll has no single apex"
            )
        if points:
            kwargs["rollposition"] = points[0]
        else:
            kwargs["rollangle"] = min(self.ROLL_ANGLE, abs(2 * np.pi * amount))
        return kwargs

    def create_elements(
        self,
        use_roll_options: bool = False,
        link_lines: bool = True,
        flip_lines: frozenset[int] = frozenset(),
        sizes: SizeGroups | None = None,
    ) -> list[a.PE]:
        """Create the elements.

        With use_roll_options the turn rolls refer to roll_option, and, if link_lines
        is set, so do the direction-changing lines (spin and roll points). The rolls
        of the lines in flip_lines are reversed when they are not linked. sizes
        (size_groups) names the comparison parameter of each matched loop and line.
        """
        pes: list[a.PE] = []
        sizes = sizes or SizeGroups()

        rolls = self.element_rolls()
        loops = self.loop_amounts(rolls)
        angles, canopies = self.path_angles(loops, rolls)
        refs = self._linked_roll_refs()[0] if use_roll_options and link_lines else {}

        for i, el in enumerate(self.fig.oels):
            match el.kind:
                case "Loop":
                    pes.append(
                        a.loop(
                            p.r(loops[i]),
                            **(
                                self._loop_roll_kwargs(
                                    rolls[i], angles[i], loops[i] * canopies[i]
                                )
                                if rolls[i] and rolls[i].roll_arr
                                else {}
                            ),
                            **({"radius": sizes.radius[i]} if i in sizes.radius else {}),
                        )
                    )
                case "Line":
                    if rolls[i] and len(rolls[i].roll_arr):
                        ref = [f"roll_option[{k}]" for k in refs.get(i, [])]
                        flip = -1 if i in flip_lines and not ref else 1
                        if rolls[i].roll_arr[0].kind == "spin":
                            # If there is a spin on the line we need to delete the previous radius and make two elements.
                            assert pes[-1].kind == "loop"
                            pes.pop(-1)
                            pes.append(
                                a.spin(
                                    ref[0]
                                    if ref
                                    else flip * rolls[i].roll_arr[0].turns * 2 * np.pi
                                )
                            )

                            if len(rolls[i].roll_arr) > 1:
                                # TODO need to know if its F3A or IMAC here
                                pes.append(
                                    a.roll(
                                        ref[1:]
                                        if ref
                                        else (
                                            flip * np.atleast_1d(rolls[i].angles())[1:]
                                        ).tolist(),
                                        rolltypes=rolls[i].rolltypes()[1:],
                                        padded=True,
                                    )
                                )
                            else:
                                pes.append(a.line())
                            pass
                        else:
                            pes.append(
                                a.roll(
                                    ref
                                    or (
                                        rolls[i].pfc_roll()
                                        if flip == 1
                                        else (
                                            -np.atleast_1d(rolls[i].angles())
                                        ).tolist()
                                    ),
                                    rolltypes=rolls[i].rolltypes(),
                                    padded=i > 0 and i < len(self.fig.oels) - 1,
                                    **(
                                        {"line_length": sizes.length[i]}
                                        if i in sizes.length
                                        else {}
                                    ),
                                )
                            )
                    elif el.bare:
                        pass  # a roll point between two curves with no roll: no line
                    elif (i > 0 and i < len(self.fig.oels) - 1) or len(self.fig.oels) == 1:
                        # a figure that is only a line ("--") keeps it
                        pes.append(
                            a.line(**({"length": sizes.length[i]} if i in sizes.length else {}))
                        )
                case "Stallturn":
                    pes.append(a.stallturn())
                case "Spin":
                    pes.append(a.spin(rolls[i].roll_arr[0].turns * 2 * np.pi))
                case "Turn":
                    linked = use_roll_options and self.turn_options() is not None
                    if self.drawn_slots is None and self.final:
                        angle = el.turnamount * np.pi * 2
                        turn_rolls = self.final.angles()
                        if linked:
                            angle = "roll_option[0]"
                            n = len(np.atleast_1d(turn_rolls))
                            turn_rolls = (
                                "roll_option[1]"
                                if n == 1
                                else [f"roll_option[{k}]" for k in range(1, n + 1)]
                            )
                        pes.append(
                            a.loop(
                                angle,
                                rolls=turn_rolls,
                                ke=np.pi / 2,
                            )
                        )
                    else:
                        # The bank rolls are passed as single item lists so the
                        # builder names them as before (e_0_0, e_2_0). Element
                        # names must stay stable to match stored segmentation.
                        bank, ke, unbank = (
                            (["roll_option[0]"], "roll_option[1]", ["roll_option[2]"])
                            if linked
                            else self.TURN_BANK
                        )
                        pes.append(a.roll(bank, padded=False))
                        pes.append(a.loop(el.turnamount * 2 * np.pi, ke=ke))
                        pes.append(a.roll(unbank, padded=False))
                case "Tailslide":
                    pes.append(a.tailslide(el.direction))
                case _:
                    raise NotImplementedError(f"cant do {el.__class__.__name__} yet")
        return pes

    def create_maninfo(
        self,
        short_name: str = None,
        entry_direction: p.Direction = None,
        exit_direction: p.Direction = None,
    ) -> a.ManInfo:
        k_factor = self.k_powered
        return ManInfo.build(
            self.fig.name,
            short_name or self.fig.short_name,
            k_factor,
            p.Position.CENTRE if entry_direction == exit_direction else p.Position.END,
            p.BoxLocation(
                direction=entry_direction
                if entry_direction is not None
                else self.entry_direction,
                orientation=self.entry,
            ),
            p.BoxLocation(direction=exit_direction, orientation=self.exit),
        )
