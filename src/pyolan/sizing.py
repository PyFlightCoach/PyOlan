"""Which loops and lines of an OLAN figure the rules compare (plan Phase S).

The aerobatic rule sets (IAC, CIVA, IMAC and their glider variants) compare sizes
inside a figure: part-loops drawn as round elements share one radius, the interior
lines of some figures are equal. PyOlan reads the shape from OpenAero's drawing
string (drawn.py marks each loop ``round`` or not); the rule set supplies the
policy, the ``[sizing]`` section of its builder.toml (``tuning.sizing_info``):

* ``corner_families``: every part-loop of these figures matches, corners included
  (Family 3, the square, diamond and octagonal loops);
* ``free_families``: no part-loop matches (the double humpty, Family 8.8);
* ``equal_lines``: the interior lines of these figures are equal;
* ``mirror_corners``: in these figures the corners pair with their mirror images,
  the first with the last (CIVA glider square loops, Figure 29: a = d, b = c);
* ``snap_lines_free``: a line with a snap roll leaves its equal-length group (IAC
  glider 34.20.4.1, CIVA glider).

In any other figure the round part-loops match. A family is an Aresti number
prefix: "7.4.3" covers 7.4.3.1 to 7.4.3.4. Without a policy nothing is linked.

The first radius group refers to the rule set's ``loop_radius``, any further group
to a ``NewComparison`` like it (``loop_radius_2``, ...); the equal lines refer to
``line_length``. A group of one is no group.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .primitives import OlanEl
from .rolls import OlanRoll

LOOP_RADIUS = "loop_radius"
LINE_LENGTH = "line_length"


@dataclass(frozen=True)
class Sizing:
    """A rule set's sizing policy (the ``[sizing]`` section of its builder.toml)."""

    corner_families: tuple[str, ...] = ()
    free_families: tuple[str, ...] = ()
    equal_lines: tuple[str, ...] = ()
    mirror_corners: tuple[str, ...] = ()
    snap_lines_free: bool = False

    KEYS = ("corner_families", "free_families", "equal_lines", "mirror_corners")

    @staticmethod
    def parse(data: Mapping[str, Any] | Sizing | None) -> Sizing | None:
        if data is None or isinstance(data, Sizing):
            return data
        unknown = set(data) - set(Sizing.KEYS) - {"snap_lines_free"}
        if unknown:
            raise ValueError(f"unknown sizing keys {sorted(unknown)}")
        return Sizing(
            **{k: tuple(str(f) for f in data.get(k, ())) for k in Sizing.KEYS},
            snap_lines_free=bool(data.get("snap_lines_free", False)),
        )


def in_families(aresti: str, families: Sequence[str]) -> bool:
    """Whether the Aresti number falls in one of the families (number prefixes)."""
    parts = aresti.split(".")
    return any(parts[: len(f.split("."))] == f.split(".") for f in families)


@dataclass
class SizeGroups:
    """The comparison parameter each element refers to, by element index."""

    radius: dict[int, str] = field(default_factory=dict)
    length: dict[int, str] = field(default_factory=dict)

    def radius_names(self) -> list[str]:
        return sorted(set(self.radius.values()), key=_group_order)

    def __bool__(self) -> bool:
        return bool(self.radius or self.length)


def _group_order(name: str) -> int:
    return int(name.rsplit("_", 1)[1]) if name[-1].isdigit() else 1


def _radius_name(k: int) -> str:
    return LOOP_RADIUS if k == 0 else f"{LOOP_RADIUS}_{k + 1}"


def _has_snap(roll: OlanRoll | None) -> bool:
    return roll is not None and any(r.kind == "snap" for r in roll.roll_arr)


def _has_spin(roll: OlanRoll | None) -> bool:
    return roll is not None and any(r.kind == "spin" for r in roll.roll_arr)


def size_groups(
    oels: Sequence[OlanEl],
    aresti: str,
    sizing: Sizing,
    rolls: Sequence[OlanRoll | None],
) -> SizeGroups:
    """The radius and line groups of a figure drawn from OpenAero's drawing string.

    oels are the figure's elements (drawn.py), aresti its catalogue number and rolls
    the roll on each element (OlanFig.element_rolls).
    """
    n = len(oels)
    # a spin replaces the loop before its line (OlanFig.create_elements)
    spun = {i - 1 for i in range(1, n) if oels[i].kind == "Line" and _has_spin(rolls[i])}
    loops = [i for i, el in enumerate(oels) if el.kind == "Loop"]

    groups: list[list[int]] = []
    if in_families(aresti, sizing.free_families):
        pass
    elif in_families(aresti, sizing.corner_families):
        if in_families(aresti, sizing.mirror_corners):
            groups = [[loops[k], loops[-1 - k]] for k in range(len(loops) // 2)]
        else:
            groups = [loops]
    else:
        groups = [[i for i in loops if oels[i].round]]
    groups = [[i for i in g if i not in spun] for g in groups]
    groups = [g for g in groups if len(g) > 1]

    out = SizeGroups()
    for k, g in enumerate(groups):
        for i in g:
            out.radius[i] = _radius_name(k)

    if in_families(aresti, sizing.equal_lines):
        lines = [
            i
            for i in range(1, n - 1)
            if oels[i].kind == "Line"
            and not oels[i].bare
            and not _has_spin(rolls[i])
            and not (sizing.snap_lines_free and _has_snap(rolls[i]))
        ]
        if len(lines) > 1:
            out.length = {i: LINE_LENGTH for i in lines}
    return out
