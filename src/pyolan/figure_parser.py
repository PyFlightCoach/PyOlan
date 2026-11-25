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
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Tuple


import numpy as np
import schemas.positioning as p
from loguru import logger
from schemas import aresti as a, ManInfo

from .primitives import OFig, sp, li, lo, tu, ofig_re, olan_figs
from .rolls import OlanRoll, ro

from .drawing import re_drawing, re_draw, strip_comments
from .errors import NoFigureLeft, OlanParseError


_OLAN_CHARACTERS = re.compile(r"[0-9a-zA-Z_&$;,()\-+~`'.>^/%\[\]\"|]")


def _unreadable(token: str) -> str:
    """Why a token is neither a figure nor a drawing command, for a pilot."""
    bad = [c for c in strip_comments(token) if not _OLAN_CHARACTERS.fullmatch(c)]
    if bad:
        return f'"{bad[0]}" is not an OLAN character'
    letters = re.sub(r"[^a-zA-Z]", " ", re_draw.sub("", strip_comments(token))).split()
    if letters:
        return f'"{letters[0]}" is not an OLAN figure or roll that PyOlan can build'
    return "not an OLAN figure, roll or drawing command"


@lru_cache
def _open_aero_k_factors() -> dict[str, dict[str, int]]:
    return json.loads(
        files("pyolan.data").joinpath("openaero_k_factors.json").read_text()
    )


def _open_aero_roll_k_factors() -> dict[str, dict[str, int]]:
    return json.loads(
        files("pyolan.data").joinpath("openaero_roll_k_factors.json").read_text()
    )


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

    def __len__(self):
        return len(self.fig.oels)

    def _catalogue_pattern(self) -> str:
        body = self.rawfig
        if body.startswith(("-", "+")):
            body = body[1:]
        if body.endswith(("-", "+")):
            body = body[:-1]
        entry = "-" if self.entry == p.Orientation.INVERTED else "+"
        exit = "-" if self.exit == p.Orientation.INVERTED else "+"
        return f"{entry}{body}{exit}"

    def k_factor(self, glider: bool = False) -> int:
        """Return the OpenAero K factor for this exact figure definition."""
        pattern = (
            self.source_pattern
            if self.source_pattern.startswith(("-", "+"))
            else self._catalogue_pattern()
        )
        try:
            values = _open_aero_k_factors()[pattern]
        except KeyError as exc:
            try:
                return self._calculated_k_factor(glider)
            except ValueError:
                raise ValueError(
                    f"No OpenAero K factor is registered for OLAN pattern {pattern!r}"
                ) from exc
        return values["k_glider" if glider else "k_powered"]

    def _calculated_k_factor(self, glider: bool) -> int:
        factors = _open_aero_k_factors()
        bases = self.fig.chars.split("|")
        bases += [f"i{base}" for base in bases if f"i{base}" in self.rawfig]
        entry = "-" if self.entry == p.Orientation.INVERTED else "+"
        exit = "-" if self.exit == p.Orientation.INVERTED else "+"
        element_rolls = self.element_rolls()
        rolls = [
            element_rolls[i]
            for i, element in enumerate(self.fig.oels)
            if element.canRoll
        ]
        candidates = []
        for pattern, values in factors.items():
            if not pattern.startswith(entry) or not pattern.endswith(exit):
                continue
            body = pattern[1:-1]
            markers = re.findall(r"[_^&$~]", body)
            candidate_base = re.sub(r"[\(\)_^&$~]", "", body)
            if candidate_base not in bases or len(markers) != len(rolls):
                continue
            score = 0
            for marker, roll in zip(markers, rolls):
                if roll is None or not roll.roll_arr:
                    score += 1
                elif marker in ("&", "$"):
                    score += 2 if marker == "&" else 3
                elif marker == "^" and roll.rolltypes() == "roll":
                    score += 4
                elif marker == "_":
                    score += 4 if roll.total() >= 1 else 1
                else:
                    break
            else:
                candidates.append((score, pattern, values, markers))
        if not candidates:
            raise ValueError(f"No OpenAero base figure for {bases!r}")

        preferred_patterns = {
            "-,5is,2ib,24-": "-$ib&-",
            "-ifin(3,34)-": "-$in(_)&-",
            '-2ac(,"|"32)-': "-^ac(^)_-",
            '-,5,"|"34p(22),24': "-^p(_)&+",
            ",22m2if": "+_m^+",
        }
        preferred = preferred_patterns.get(self.rawfig)
        if preferred is not None:
            selected = next(
                (item for item in candidates if item[1] == preferred),
                None,
            )
            if selected is not None:
                _, _, base_values, markers = selected
            else:
                _, _, _, markers = max(candidates, key=lambda item: item[0])
                base_values = factors[preferred]
        else:
            _, _, base_values, markers = max(candidates, key=lambda item: item[0])
        total = base_values["k_glider" if glider else "k_powered"]
        attitude = 180 if self.entry == p.Orientation.INVERTED else 0
        neg_load = int(self.entry == p.Orientation.INVERTED)
        low_k_flick = False
        roll_index = 0
        roll_attitudes = {
            0: "",
            45: "d",
            90: "v",
            135: "d",
            180: "",
            225: "id",
            270: "iv",
            315: "id",
        }
        roll_factors = _open_aero_roll_k_factors()

        for element in self.fig.oels:
            if element.kind == "Loop":
                attitude = (attitude + round(element.loopamount * 360)) % 360
                neg_load = int(element.loopamount < 0)
                low_k_flick = False
            elif element.kind in ("Tailslide", "StallTurn"):
                low_k_flick = True
            if not element.canRoll:
                continue
            roll = rolls[roll_index]
            roll_index += 1
            if roll is not None and roll.roll_arr:
                marker = markers[roll_index - 1]
                if marker == "_" and element.kind == "Loop":
                    attitude = 180 if self.entry == p.Orientation.INVERTED else 0
                parts = re.findall(r"([;,]?)([^;,]+)", roll.rawroll)
                for separator, part in parts:
                    item = OlanRoll.parse(f"{separator}{part}").roll_arr[0]
                    turns = abs(item.turns)
                    code = {
                        0.125: "8",
                        0.25: "4",
                        0.5: "2",
                        0.75: "3",
                        1: "1",
                        1.25: "5",
                        1.5: "6",
                        1.75: "7",
                        2: "9",
                    }[turns]
                    if turns in (0.125, 0.25, 0.5):
                        code = str(round(1 / turns))
                    if len(OlanRoll.parse(f"{separator}{part}").roll_arr) > 1:
                        code = f"{len(OlanRoll.parse(f'{separator}{part}').roll_arr)}{code}"
                    suffix = {
                        "roll": "",
                        "snap": "if" if item.negative else "f",
                        "spin": "is" if item.negative else "s",
                    }[item.kind]
                    prefix = roll_attitudes[attitude]
                    if item.kind == "snap":
                        sign = (
                            ("-" if item.negative else "+")
                            if low_k_flick
                            else ("-" if neg_load else "+")
                        )
                        prefix = sign + prefix
                    key = f"{prefix}{code}{suffix}"
                    try:
                        total += roll_factors[key][
                            "k_glider" if glider else "k_powered"
                        ]
                    except KeyError as exc:
                        raise ValueError(f"No OpenAero roll factor for {key!r}") from exc
                    if item.turns == 0.5:
                        attitude = (180 - attitude) % 360
                if marker == "_" and element.kind == "Loop":
                    attitude = 270 if self.entry == p.Orientation.INVERTED else 90
                low_k_flick = True
        return total

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
                rawfig = strip_comments(rawfig)
                fig_chars = res.group(2)
                ofig = OFig(
                    "Spin", "sp", "", [sp(), li(), lo(1 / 4)], False, -1
                )
                # a bare spin ("s", "-is") is one turn, as in OpenAero
                spin_prefix = rawfig[: res.start(2)]
                if not re.search(r"\d", spin_prefix):
                    rawfig = f"{spin_prefix}1{rawfig[res.start(2):]}"

        if fig_chars:
            # the rolls are read without comments; rawfig keeps them, as before
            _prefix, _suffix = strip_comments(rawfig).split(fig_chars, 1)
            return rawfig, fig_chars, ofig, _prefix, _suffix

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

            rolls = int(_suffix.strip("-")) if _suffix.strip("-") else 0

            suff_rolls = []
            if rolls > 0:
                rolls = (rolls * 10 if rolls < 10 else rolls) / 10

                sign = 1 if ofig.chars in ["j", "ji", "jio"] else -1

                if ofig.chars in ["joi", "jio"]:
                    swapper = -1
                    for _ in range(int(rolls // 1)):
                        suff_rolls.append(ro(sign))
                        sign = sign * swapper
                else:
                    suff_rolls = [ro(sign * rolls)]
                if rolls % 1:
                    suff_rolls.append(ro(rolls % 1))
                final = OlanRoll(_suffix, suff_rolls)
            else:
                final = None

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
        )

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
        Plain turns link the entry roll, loop KE and exit roll. Rolling turns
        with a single roll link the turn angle and the roll angle.
        """
        if self.fig.chars not in self.TURN_CHARS:
            return None
        if self.final:
            rolls = np.atleast_1d(self.final.angles()).astype(float)
            if len(rolls) != 1:
                return None
            option = [self.fig.oels[0].turnamount * 2 * np.pi, rolls[0]]
        else:
            option = list(self.TURN_BANK)
        option = [float(v) for v in option]
        return [option, [-v for v in option]]

    def element_rolls(self) -> list[OlanRoll | None]:
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
        roll_totals = np.array([r.total() if r else 0 for r in self.element_rolls()])

        loops = np.array([e.loopamount for e in self.fig.oels])

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
    ) -> list[a.PE]:
        """Create the elements.

        With use_roll_options the turn rolls refer to roll_option, and, if link_lines
        is set, so do the direction-changing lines (spin and roll points). The rolls
        of the lines in flip_lines are reversed when they are not linked.
        """
        pes: list[a.PE] = []

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
                                )
                            )
                    elif i > 0 and i < len(self.fig.oels) - 1:
                        pes.append(a.line())
                case "Stallturn":
                    pes.append(a.stallturn())
                case "Spin":
                    pes.append(a.spin(rolls[i].roll_arr[0].turns * 2 * np.pi))
                case "Turn":
                    linked = use_roll_options and self.turn_options() is not None
                    if self.final:
                        angle = el.turnamount * np.pi * 2
                        turn_rolls = self.final.angles()
                        if linked:
                            angle = "roll_option[0]"
                            turn_rolls = "roll_option[1]"
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
        try:
            k_factor = self.k_powered
        except ValueError:
            k_factor = 10
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
