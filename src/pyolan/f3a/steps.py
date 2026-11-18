"""The step form shared by family templates and step-by-step descriptions.

A figure is a list of clauses (entry, lines, rolls, loops, stall turns, turns,
exit). resolve() flies them with a body frame to decide what the words leave
open:

- whether a loop is pulled, pushed or flown in knife-edge (from the wing and
  belly directions relative to the figure plane), and its sign;
- the sense of a loop that only gives an amount (from the line that follows,
  preferring to keep travelling in the entry direction for centre figures);
- the connecting quarter loops into the first line and out of the last;
- the direction of each quarter roll (from the stated exit attitude and the
  knife-edge requirements).

World axes: X along the entry heading, Y to the left, Z up. The path angle in
the figure plane is in turns, 0 along +X and 1/4 straight up. The body frame
holds the nose (bx), right wing (by) and belly (bz) directions, as the
flightanalysis elements use them: a loop angle is a rotation about by
(positive pulls), a knife-edge loop angle a rotation about bz (positive yaws
towards the right wing) and a roll a rotation about bx (positive rolls right).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np
import schemas.positioning as p
from schemas import aresti as a

from ..figure_parser import horizontal_fractions
from ..rolls import OlanRoll
from .errors import F3AParseError
from .rolls import is_quarter, signed

X = np.array([1.0, 0.0, 0.0])
Y = np.array([0.0, 1.0, 0.0])
Z = np.array([0.0, 0.0, 1.0])
PLANE_AXIS = -Y  # rotating about it by a positive angle turns +X towards +Z
DOWN = -Z  # rotating about it by a positive angle turns right
ROLL_ANGLE = np.pi / 2  # the part of a loop a roll in it spans (as OlanFig)
KE = np.pi / 2


# ---------------------------------------------------------------- clauses


@dataclass
class Entry:
    attitude: p.Orientation


@dataclass
class Line:
    """A line. angles are the allowed path angles (None: whatever it is)."""

    angles: frozenset[Fraction] | None = None
    knife_edge: bool | None = None
    label: str = ""
    length: str | None = None  # a builder expression such as "2*loop_radius"


@dataclass
class Roll:
    """A roll on the current line. A line is started if a loop came before."""

    roll: OlanRoll


@dataclass
class Loop:
    amount: Fraction
    sense: int | None = None  # +1 towards +Z when travelling +X, -1 the other way
    pull: bool | None = None  # True pulled, False pushed
    knife_edge: bool | None = None
    roll: OlanRoll | None = None
    integrated: bool = False  # the roll spans the whole loop, not 90 degrees of it


@dataclass
class StallTurn:
    pass


@dataclass
class Turn:
    """A level turn; rolls in it are towards the inside or the outside."""

    amount: Fraction
    roll: OlanRoll | None = None
    inside: bool | None = None


@dataclass
class Exit:
    attitude: p.Orientation | None = None


Clause = Entry | Line | Roll | Loop | StallTurn | Turn | Exit

UP = frozenset({Fraction(1, 4)})
DOWN_LINE = frozenset({Fraction(3, 4)})
VERTICAL = UP | DOWN_LINE
LEVEL = frozenset({Fraction(0), Fraction(1, 2)})


# ---------------------------------------------------------------- resolved items


@dataclass
class RLine:
    rolls: list[OlanRoll] = field(default_factory=list)
    linked: bool = False  # the roll direction is linked to the mirror option
    length: str | None = None  # a builder expression for the line length

    @property
    def roll(self) -> OlanRoll | None:
        if not self.rolls:
            return None
        return OlanRoll(
            ",".join(r.rawroll for r in self.rolls),
            [o for r in self.rolls for o in r.roll_arr],
        )


@dataclass
class RLoop:
    angle: float  # element angle, radians
    ke: bool
    start: Fraction  # path angle at the start, turns
    geometric: Fraction  # signed change in path angle, turns
    roll: OlanRoll | None = None
    integrated: bool = False


@dataclass
class RStallTurn:
    pass


@dataclass
class RTurn:
    angle: float
    roll: float


Item = RLine | RLoop | RStallTurn | RTurn


@dataclass
class Resolved:
    items: list[Item]
    entry: p.Orientation
    exit: p.Orientation
    reverses: bool  # the exit heading is opposite to the entry heading
    entry_height: p.Height
    exit_height: p.Height


# ---------------------------------------------------------------- geometry


def _rotate(frame: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """Rotate the frame's columns about a world axis (Rodrigues)."""
    axis = axis / np.linalg.norm(axis)
    k = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    rot = np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k
    return rot @ frame


def _aligned(v: np.ndarray, axis: np.ndarray) -> int:
    """+1 or -1 if v is along axis, 0 otherwise."""
    d = float(v @ axis)
    if abs(abs(d) - 1) < 1e-6:
        return int(np.sign(d))
    return 0


def _turns(x: float | Fraction) -> float:
    return float(x) * 2 * np.pi


@dataclass
class _Flight:
    frame: np.ndarray
    theta: Fraction = Fraction(0)
    heading: int = 1  # sign of the horizontal travel after level turns (not used yet)
    z: float = 0.0
    x: float = 0.0
    zs: list[float] = field(default_factory=lambda: [0.0])

    @property
    def bx(self):
        return self.frame[:, 0]

    @property
    def by(self):
        return self.frame[:, 1]

    @property
    def bz(self):
        return self.frame[:, 2]

    def plane_loop(self, geometric: Fraction) -> tuple[float, bool]:
        """Loop by a geometric amount in the figure plane: (element angle, ke)."""
        pitch = _aligned(self.by, PLANE_AXIS)
        yaw = _aligned(self.bz, PLANE_AXIS)
        if pitch:
            angle, ke = _turns(geometric) * pitch, False
        elif yaw:
            angle, ke = _turns(geometric) * yaw, True
        else:
            raise F3AParseError(
                "the wings are neither level nor vertical in the figure plane "
                f"at path angle {self.theta}"
            )
        # path for the heights (radius 0.5, unit lines)
        n = max(2, int(abs(geometric) * 32))
        start = float(self.theta)
        for i in range(1, n + 1):
            t0 = start + float(geometric) * (i - 1) / n
            t1 = start + float(geometric) * i / n
            ds = 0.5 * abs(_turns(geometric)) / n
            tm = (t0 + t1) / 2
            self.x += ds * np.cos(_turns(tm))
            self.z += ds * np.sin(_turns(tm))
            self.zs.append(self.z)
        self.frame = _rotate(self.frame, PLANE_AXIS, _turns(geometric))
        self.theta = (self.theta + geometric) % 1
        return angle, ke

    def line(self):
        self.x += np.cos(_turns(self.theta))
        self.z += np.sin(_turns(self.theta))
        self.zs.append(self.z)

    def roll(self, roll: OlanRoll):
        self.frame = _rotate(self.frame, self.bx, _turns(roll.total()))

    def knife_edge(self) -> bool:
        return _aligned(self.bz, PLANE_AXIS) != 0

    def attitude(self) -> p.Orientation:
        if self.theta not in LEVEL:
            raise F3AParseError(f"the figure does not end level (path angle {self.theta})")
        return p.Orientation.UPRIGHT if self.bz @ Z < 0 else p.Orientation.INVERTED


def _initial_frame(attitude: p.Orientation) -> np.ndarray:
    frame = np.column_stack([X, PLANE_AXIS, DOWN])
    if attitude == p.Orientation.INVERTED:
        frame = _rotate(frame, X, np.pi)
    return frame


def _height(z: float, zs: list[float]) -> p.Height:
    lo, hi = min(zs), max(zs)
    if hi - lo < 1e-6:
        return p.Height.BTM
    f = (z - lo) / (hi - lo)
    if f < 0.25:
        return p.Height.BTM
    if f > 0.75:
        return p.Height.TOP
    return p.Height.MID


def _shortest(start: Fraction, targets: frozenset[Fraction], forward: bool) -> Fraction:
    """The signed geometric change from start to the nearest target.

    Ties go to the target that travels forwards (+X) when forward, else back.
    """
    options = []
    for target in targets:
        d = (target - start) % 1
        for change in (d, d - 1):
            options.append(change)
    best = min(abs(o) for o in options)
    nearest = sorted({o for o in options if abs(o) == best})
    if len(nearest) > 1:
        sign = 1 if forward else -1
        preferred = [
            o for o in nearest if sign * np.cos(_turns(start + o)) > 1e-9
        ]
        if len(preferred) != 1:
            raise F3AParseError(
                f"cannot tell which way to turn from path angle {start} to {sorted(targets)}"
            )
        return preferred[0]
    return nearest[0]


def _next_angles(clauses: list[Clause], i: int) -> frozenset[Fraction] | None:
    """The path angles the clauses after a loop at i allow, if they say."""
    for clause in clauses[i + 1:]:
        match clause:
            case Line(angles=angles) if angles is not None:
                return angles
            case Line() | Roll():
                continue
            case StallTurn():
                return UP
            case Exit():
                return LEVEL
            case _:
                return None
    return None


# ---------------------------------------------------------------- resolution


class _Branch(Exception):
    """A loop whose sense the description leaves open; both are valid."""

    def __init__(self, index: int, senses: list[int]):
        self.index, self.senses = index, senses


def _fly(
    clauses: list[Clause],
    signs: dict[int, int],
    forward: bool,
    senses: dict[int, int] | None = None,
) -> tuple[list[Item], _Flight, p.Orientation]:
    entry = clauses[0]
    if not isinstance(entry, Entry):
        raise F3AParseError("a figure must start with its entry attitude")
    flight = _Flight(_initial_frame(entry.attitude))
    items: list[Item] = [RLine()]

    def current_line() -> RLine:
        if not isinstance(items[-1], RLine):
            items.append(RLine())
            flight.line()
        return items[-1]

    def add_loop(
        geometric: Fraction,
        roll: OlanRoll | None,
        knife_edge: bool | None,
        integrated: bool = False,
    ):
        start = flight.theta
        angle, ke = flight.plane_loop(geometric)
        if knife_edge is not None and knife_edge != ke:
            raise F3AParseError(
                f"the {abs(geometric)} loop from path angle {start} is "
                f"{'' if ke else 'not '}in knife-edge"
            )
        items.append(RLoop(angle, ke, start, geometric, roll, integrated))
        if roll is not None:
            flight.roll(roll)

    for i, clause in enumerate(clauses[1:], start=1):
        match clause:
            case Line(angles=angles, knife_edge=knife_edge, length=length):
                if angles is not None and flight.theta not in angles:
                    if len(items) == 1 and not items[0].rolls:
                        add_loop(_shortest(flight.theta, angles, forward), None, None)
                    else:
                        raise F3AParseError(
                            f"line at path angle {flight.theta}, expected {sorted(angles)}"
                        )
                if length is not None:
                    current_line().length = length
                else:
                    current_line()
                if knife_edge is not None and knife_edge != flight.knife_edge():
                    raise F3AParseError(
                        f"line at path angle {flight.theta} is "
                        f"{'' if flight.knife_edge() else 'not '}in knife-edge"
                    )
            case Roll(roll=roll):
                line = current_line()
                sign = signs.get(i, 1)
                roll = signed(roll, sign)
                line.rolls.append(roll)
                line.linked = line.linked or i in signs
                flight.roll(roll)
            case Loop(
                amount=amount, sense=sense, pull=pull, knife_edge=ke, roll=roll,
                integrated=integrated,
            ):
                if sense is None and pull is not None:
                    pitch = _aligned(flight.by, PLANE_AXIS)
                    if not pitch:
                        raise F3AParseError("a pulled or pushed loop needs level wings")
                    sense = (1 if pull else -1) * pitch
                if sense is None and senses and i in senses:
                    sense = senses[i]
                if sense is not None:
                    geometric = amount * sense
                else:
                    targets = _next_angles(clauses, i)
                    candidates = [
                        s for s in (1, -1)
                        if targets is None or (flight.theta + amount * s) % 1 in targets
                    ]
                    if len(candidates) > 1:
                        # the pilot may fly either; the one that keeps the travel
                        # direction (as the drawings show) comes first
                        pref = 1 if forward else -1
                        candidates.sort(
                            key=lambda s: -pref * np.cos(_turns(flight.theta + amount * s))
                        )
                        raise _Branch(i, candidates)
                    if len(candidates) != 1:
                        raise F3AParseError(
                            f"cannot tell which way the {amount} loop goes from path angle {flight.theta}"
                        )
                    geometric = amount * candidates[0]
                add_loop(
                    geometric, signed(roll, signs.get(i, 1)) if roll else None, ke, integrated
                )
            case StallTurn():
                if flight.theta != Fraction(1, 4) or not isinstance(items[-1], RLine):
                    raise F3AParseError("a stall turn needs a vertical upline")
                items.append(RStallTurn())
                flight.frame = _rotate(flight.frame, flight.bz, np.pi)
                flight.theta = Fraction(3, 4)
            case Turn(amount=amount, roll=roll, inside=inside):
                if flight.theta not in LEVEL:
                    raise F3AParseError("a turn must be flown level")
                yaw = _aligned(flight.bz, DOWN)
                if not yaw:
                    raise F3AParseError("a level turn needs level wings")
                # right turn; a roll to the inside of a right turn rolls right
                angle = _turns(amount) * yaw
                roll_angle = 0.0
                if roll is not None:
                    if inside is None:
                        raise F3AParseError("say whether the rolls are inside or outside")
                    roll_angle = _turns(roll.total()) * (1 if inside else -1)
                flight.frame = _rotate(flight.frame, DOWN, _turns(amount))
                flight.frame = _rotate(flight.frame, flight.bx, roll_angle)
                items.append(RTurn(angle, roll_angle))
                if amount % 1:
                    raise F3AParseError("only whole circles are supported")
            case Exit(attitude=attitude):
                if flight.theta not in LEVEL:
                    add_loop(_shortest(flight.theta, LEVEL, forward), None, None)
                if not isinstance(items[-1], RLine):
                    items.append(RLine())
                if attitude is not None and flight.attitude() != attitude:
                    raise F3AParseError(
                        f"exits {flight.attitude().name.lower()}, expected {attitude.name.lower()}"
                    )
            case Entry():
                raise F3AParseError("the entry attitude is given twice")
    if not isinstance(clauses[-1], Exit):
        raise F3AParseError("a figure must end with its exit")
    return items, flight, entry.attitude


def resolve(clauses: list[Clause], forward: bool = True) -> list[Resolved]:
    """Every way of flying the clauses that the description allows.

    A loop whose sense the words leave open (both senses reach the next line)
    gives one resolution for each sense, the one keeping the travel direction
    first. Roll directions are not branched: see _resolve_signs.
    """
    return _resolve_senses(clauses, forward, {})


def _resolve_senses(
    clauses: list[Clause], forward: bool, senses: dict[int, int]
) -> list[Resolved]:
    try:
        return [_resolve_signs(clauses, forward, senses)]
    except _Branch as branch:
        results: list[Resolved] = []
        errors: list[str] = []
        for sense in branch.senses:
            try:
                results += _resolve_senses(clauses, forward, senses | {branch.index: sense})
            except F3AParseError as exc:
                errors.append(str(exc))
        if not results:
            raise F3AParseError("; ".join(dict.fromkeys(errors)))
        return results


def _resolve_signs(
    clauses: list[Clause], forward: bool, senses: dict[int, int]
) -> Resolved:
    """Fly the clauses, choosing quarter roll directions that satisfy them all.

    The first quarter roll is a free choice (the mirror image is equally valid),
    so the combinations are tried with earlier rolls positive first.
    """
    free = [
        i for i, c in enumerate(clauses)
        if (isinstance(c, Roll) and is_quarter(c.roll))
        or (isinstance(c, Loop) and is_quarter(c.roll))
    ]
    errors = []
    for combination in itertools.product([1, -1], repeat=len(free)):
        signs = dict(zip(free, combination))
        try:
            items, flight, entry = _fly(clauses, signs, forward, senses)
        except F3AParseError as exc:
            errors.append(str(exc))
            continue
        exit_attitude = flight.attitude()
        return Resolved(
            items=items,
            entry=entry,
            exit=exit_attitude,
            reverses=bool(flight.bx @ X < 0),
            entry_height=_height(0.0, flight.zs),
            exit_height=_height(flight.z, flight.zs),
        )
    raise F3AParseError(errors[0] if len(set(errors)) == 1 else "; ".join(dict.fromkeys(errors)))


# ---------------------------------------------------------------- elements


def _loop_roll_kwargs(item: RLoop) -> dict:
    roll = item.roll
    kwargs: dict[str, object] = dict(
        rolls=roll.pfc_roll(), rolltypes=roll.rolltypes(), rollangle=ROLL_ANGLE
    )
    if item.integrated:
        # spread over the whole loop
        kwargs["rollangle"] = abs(_turns(item.geometric))
        kwargs["rollposition"] = 0.5
        return kwargs
    points = horizontal_fractions(float(item.start), float(item.geometric))
    if len(points) > 1:
        raise F3AParseError("a roll in a loop needs a single apex or nadir")
    if points:
        kwargs["rollposition"] = points[0]
    else:
        kwargs["rollangle"] = min(ROLL_ANGLE, abs(_turns(item.geometric)))
    return kwargs


def mirror_parameters(items: list[Item]) -> list[float]:
    """The values that change sign when the figure is mirrored in its plane.

    Only knife-edge loops, turns and the quarter rolls that set the knife-edge
    side need linking; other roll directions are left to the builder.
    """
    values: list[float] = []
    for item in items:
        match item:
            case RLine(linked=True):
                values.extend(np.atleast_1d(item.roll.angles()).astype(float).tolist())
            case RLoop(ke=True):
                values.append(float(item.angle))
            case RTurn():
                values.extend([float(item.angle), float(item.roll)])
    return values


ROLL_LINE = "roll_line_length"
ROLL_LINE_DEFAULT = 20.0  # m; a line next to a roll that starts or ends a figure


def figure_ndmps(items: list[Item]) -> dict[str, a.NewComparison]:
    """The comparison parameter shared by the lines next to the start and end rolls.

    F3A puts a line between a roll that starts or ends a figure and its
    neighbouring loop. Those lines are compared with each other, and need not
    match the figure's other lines.
    """
    last = len(items) - 1
    first_roll = last > 0 and isinstance(items[0], RLine) and items[0].rolls
    end_roll = last > 0 and isinstance(items[last], RLine) and items[last].rolls
    if first_roll or end_roll:
        return {ROLL_LINE: a.NewComparison(value=ROLL_LINE_DEFAULT, like="line_length")}
    return {}


def create_elements(items: list[Item], linked: bool) -> list[a.PE]:
    """The elements; with linked the mirror parameters refer to roll_option."""
    pes: list[a.PE] = []
    k = itertools.count()

    def ref() -> str:
        return f"roll_option[{next(k)}]"

    last = len(items) - 1
    for i, item in enumerate(items):
        match item:
            case RLine():
                padded = 0 < i < last
                roll = item.roll
                if roll is not None:
                    if i == last and i > 0:
                        # F3A: a roll that ends the figure follows a line, and the
                        # figure finishes at the end of the roll
                        pes.append(a.line(length=ROLL_LINE))
                    if linked and item.linked:
                        rolls = [ref() for _ in roll.roll_arr]
                    else:
                        rolls = roll.pfc_roll()
                    extra = {"line_length": item.length} if item.length and padded else {}
                    pes.append(a.roll(rolls, rolltypes=roll.rolltypes(), padded=padded, **extra))
                    if i == 0 and last > 0:
                        # and so does one that starts it
                        pes.append(a.line(length=ROLL_LINE))
                elif padded:
                    pes.append(a.line(length=item.length) if item.length else a.line())
            case RLoop():
                angle = ref() if linked and item.ke else float(item.angle)
                kwargs = _loop_roll_kwargs(item) if item.roll is not None else {}
                if item.ke:
                    kwargs["ke"] = KE
                pes.append(a.loop(angle, **kwargs))
            case RStallTurn():
                pes.append(a.stallturn())
            case RTurn():
                if linked:
                    pes.append(a.loop(ref(), rolls=ref(), ke=KE))
                else:
                    pes.append(a.loop(float(item.angle), rolls=float(item.roll), ke=KE))
    return pes
