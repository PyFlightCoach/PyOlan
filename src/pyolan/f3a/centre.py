"""Centre marks for F3A centre figures (the numbered catalogue groups).

Scoring gives a centring deduction only where a figure marks what must be centred
in the box: a ``schemas.positioning.MBTags.CENTRE`` marker between two elements
(the start of the element after it) or a ``centred`` element (its middle). The
known schedules (P25, P27) mark the points on the figure's axis of symmetry:

- a figure that starts and ends level on either side of its axis (humpty bump,
  triangle, square loop, loop) has a marker at its start and at its end, and the
  middle element is centred: for a humpty bump the start of the pull-up and the
  end of the pull-out, and the middle of the half loop;
- a spin has a marker at its start (the vertical line is the axis);
- a lone roll, and the double Immelmann, centre their middle element only.

The rule is a function of the family's group number, with the default "both" for
the symmetric figures. The middle is the middle element of the figure; where a
group's elements are not laid out symmetrically it is named explicitly below.
Lettered groups (turnarounds and end figures) are not marked.
"""

from __future__ import annotations

from collections.abc import Callable

import schemas.positioning as p
from schemas import aresti as a

PEs = list[a.PE]
# (element indices to centre, indices of the boundaries to mark: i is the boundary before element i)
Marks = tuple[list[int], list[int]]


def _middle(pes: PEs) -> tuple[list[int], list[int]]:
    """The middle element of an odd number of elements, the middle boundary of an even number."""
    n = len(pes)
    return ([n // 2], []) if n % 2 else ([], [n // 2])


def _after_loop(nth: int) -> Callable[[PEs], tuple[list[int], list[int]]]:
    """The element after the nth loop (the far leg of a square loop, the 45 degree line of a figure N)."""

    def middle(pes: PEs) -> tuple[list[int], list[int]]:
        loops = [i for i, pe in enumerate(pes) if pe.kind == "loop"]
        if len(loops) >= nth and loops[nth - 1] + 1 < len(pes):
            return [loops[nth - 1] + 1], []
        return _middle(pes)

    return middle


def _after_first_loop(pes: PEs) -> tuple[list[int], list[int]]:
    """The middle of what follows the first loop (the diamond in a loop: its far corner)."""
    first = next((i for i, pe in enumerate(pes) if pe.kind == "loop"), -1) + 1
    centred, bounds = _middle(pes[first:])
    return [first + i for i in centred], [first + i for i in bounds]


def _both(find_middle: Callable[[PEs], tuple[list[int], list[int]]] = _middle) -> Callable[[PEs], Marks]:
    """Markers at the start and end of the figure, and the middle."""

    def marks(pes: PEs) -> Marks:
        centred, bounds = find_middle(pes) if len(pes) >= 3 else ([], [])
        return centred, sorted({0, len(pes), *bounds})

    return marks


def _ends_only(pes: PEs) -> tuple[list[int], list[int]]:
    return [], []


def _middle_only(pes: PEs) -> Marks:
    return _middle(pes)


def _start_only(pes: PEs) -> Marks:
    return [], [0]


def _double_key(pes: PEs) -> Marks:
    """Both vertical lines are centred: the first and the fourth roll."""
    rolls = [i for i, pe in enumerate(pes) if pe.kind == "roll"]
    return [rolls[0], rolls[3]], []


RULES: dict[str, Callable[[PEs], Marks]] = {
    # loops: P25's [CENTRE, loop, CENTRE]; a knife-edge loop's middle element is several
    # elements the builder cannot find the middle of
    "01": _both(_ends_only),
    "05": _both(_after_loop(2)),  # square loop: the far side
    "19": _start_only,
    "21": _middle_only,
    "23": _middle_only,
    "24": _double_key,
    "26": _both(_after_loop(2)),  # figure N: the 45 degree line
    "30": _both(_after_first_loop),
}
DEFAULT = _both()


def centre_marks(elements: PEs, group: str | None) -> list[a.PE | int]:
    """The elements with the centre marks of the group's family (none for a lettered group)."""
    if group is None or not group.isdigit() or not elements:
        return list(elements)
    centred, bounds = RULES.get(group.zfill(2), DEFAULT)(elements)
    out: list[a.PE | int] = []
    for i, pe in enumerate(elements):
        if i in bounds:
            out.append(p.MBTags.CENTRE)
        out.append(a.centred(pe) if i in centred else pe)
    if len(elements) in bounds:
        out.append(p.MBTags.CENTRE)
    return out
