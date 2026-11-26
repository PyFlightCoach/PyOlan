"""Rolls in loops are centred on the apex or nadir of the template.

IAC 27.12.1-27.12.2: "The rolls must be centered symmetrically about the apex or
nadir and be integrated into the radius." The template is built with the IAC
builder, whose roll width is 90 degrees, so the rolling section of a centred loop
runs from +45 to -45 degrees of path elevation (or -45 to +45 at a nadir).
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest
from pytest import fixture
from tuning.builders import load_builder

from pyolan.figure_parser import OlanFig, horizontal_fractions
from pyolan.parser import parse_olan

CATALOGUE = json.loads(
    (Path(__file__).parent / "data" / "openaero" / "figures.json").read_text()
)["figures"]

# One OLAN figure with a roll in the loop for each catalogue code that has an
# embedded ("!") roll, then the figures the plan names. A loop's roll is written
# after it ("o1"): OpenAero ignores a roll in brackets where the figure has no
# bracketed slot ("o(2)"), and PyOlan reads it the same way since Phase D.
EMBEDDED_ROLL_FIGURES = {
    "o": "o1",
    "io": "io1",
    "ao": "ao(1)",
    "iao": "iao(1)",
    "rao": "rao(1)",
    "irao": "irao(1)",
    "or": "or(1)",
    "ior": "ior(1)",
    "ro": "ro(1)",
    "iro": "iro(1)",
    "rp": "rp(1)",
    "irp": "irp(1)",
    "p": "p(2)",
    "ip": "ip(2)",
    "rpp": "rpp(2)",
    "pp": "pp(2)",
    "rq": "rq(1)",
    "q": "q(1)",
    "oj": "oj1",
    "ioj": "ioj1",
}
# "ph" and "pbh" (PyOlan aliases of "hp", the same figure) were here too: OpenAero
# has no such figure, so since C3 parse_olan refuses them (no K). "hp1" was here
# too: OpenAero draws the roll of its hammer P loop on the exit line, after the loop.
EXTRA_FIGURES = ["p(2,f)", "o2,f-"]


@fixture(scope="session")
def mb():
    return load_builder("IAC", category="unlimited")


def _elevation(state) -> np.ndarray:
    """World path elevation in degrees, up positive."""
    vel = state.wvel
    return np.degrees(np.arctan2(vel.z, np.hypot(vel.x, vel.y)))


def rolling_sections(olan: str, mb) -> list[tuple[float, float]]:
    """Elevation at the start and end of the rolling section of each rolling loop.

    The section runs from the end of pad1 to the start of pad2, which is every
    template element of the loop except the pads.
    """
    figure = parse_olan(olan, mb)[0]
    names = list(figure.template.labels.element.keys())
    sections = []
    for index, pe in enumerate(figure.aresti.elements):
        if pe.kind != "loop" or "rolls" not in pe.kwargs:
            continue
        members = [n for n in names if re.fullmatch(rf"e_{index}(_\d+(_pause)?)?", n)]
        first = _elevation(getattr(figure.template.element, members[0]))
        last = _elevation(getattr(figure.template.element, members[-1]))
        sections.append((float(first[0]), float(last[-1])))
    return sections


@pytest.mark.parametrize(
    "olan",
    [*EMBEDDED_ROLL_FIGURES.values(), *EXTRA_FIGURES],
)
def test_rolling_section_is_centred_on_the_apex_or_nadir(olan, mb):
    sections = rolling_sections(olan, mb)

    assert len(sections) == 1
    start, end = sections[0]
    assert start == pytest.approx(-end, abs=1.5)
    assert abs(start) == pytest.approx(45, abs=1.5)


@pytest.mark.parametrize("olan", ["p(f)", "of", "p(2f)"])
def test_snap_only_section_is_a_point_at_the_apex(olan, mb):
    (start, end), = rolling_sections(olan, mb)

    assert start == pytest.approx(0, abs=1.5)
    assert end == pytest.approx(0, abs=1.5)


def test_xm_rolls_are_between_its_eighth_loops(mb):
    # OpenAero's xm (0.101) draws its rolls between the 45 degree curves, not in
    # them (Phase D; PyOlan's own xm had them in the curves)
    figure = parse_olan("1xm(1)1", mb)[0]

    assert [pe.kind for pe in figure.aresti.elements] == ["loop", "roll", "loop", "roll", "loop", "roll", "loop"]
    assert not [pe for pe in figure.aresti.elements if pe.kind == "loop" and "rolls" in pe.kwargs]


@pytest.mark.parametrize(
    ("start", "amount", "expected"),
    [
        (0, 1, [0.5]),  # o: the apex is half way round
        (0, 0.75, [2 / 3]),  # p, ao: level when 1/2 a turn has been made
        (0, 0.875, [4 / 7]),  # q
        (0.25, -0.75, [1 / 3]),  # ro: from vertical, level after a quarter
        (0.25, -0.5, [0.5]),  # pp: the top of the push half loop
        (0, -0.75, [2 / 3]),  # the same loops flown the other way
        (0, 0.25, []),  # ends vertical: no interior level point
        (0.25, 0.25, []),  # starts vertical and ends level: only at the end
        (0, 0.125, []),  # level at the start only
        (-0.25, 0.5, [0.5]),  # from vertical down through the bottom
    ],
)
def test_horizontal_fractions(start, amount, expected):
    np.testing.assert_allclose(horizontal_fractions(start, amount), expected)


def test_a_loop_that_is_level_twice_has_no_single_apex():
    figure = OlanFig.take(["o1"])[0]
    roll = figure.final

    with pytest.raises(ValueError, match="more than one"):
        figure._loop_roll_kwargs(roll, 0.0, 1.5)


def test_a_loop_with_no_interior_level_point_caps_the_roll_width():
    figure = OlanFig.take(["o1"])[0]
    roll = figure.final

    kwargs = figure._loop_roll_kwargs(roll, 0.0, 0.125)

    assert kwargs["rollangle"] == pytest.approx(np.pi / 4)
    assert "rollposition" not in kwargs


def _catalogue_roll_arcs():
    """For each embedded-roll code, its OpenAero arcs and which one carries the roll."""
    seen = {}
    for figure in CATALOGUE:
        code = figure["base_code"]
        if code in seen or not figure["pattern"].startswith("+"):
            continue
        plan = figure["semantics"]["render_plan"]
        if not any(item["kind"] == "embedded_roll" for item in plan):
            continue
        arcs, carrier = [], None
        for item in plan:
            if item["kind"] == "arc":
                arcs.append(item["angle"])
            elif item["kind"] == "embedded_roll":
                carrier = len(arcs) - 1
        seen[code] = (arcs, carrier, plan)
    return seen


ROLL_ARCS = _catalogue_roll_arcs()


def _merged_open_aero_loops(plan):
    """OpenAero arcs joined into loops, as PyOlan builds them.

    Neighbouring arcs of the same sign with only the roll marker between them are
    one loop (ao is a 90 and a 180 degree arc, which PyOlan builds as a 3/4 loop).
    Returns [angle, carries_roll] per loop.
    """
    loops = []
    after_arc = False
    for item in plan:
        if item["kind"] == "arc":
            if loops and after_arc and (loops[-1][0] > 0) == (item["angle"] > 0):
                loops[-1][0] += item["angle"]
            else:
                loops.append([item["angle"], False])
            after_arc = True
        elif item["kind"] == "embedded_roll":
            loops[-1][1] = True
        elif not (
            # the slot of the roll in the top belongs to the loop; a fixed quarter
            # roll ("4", oj and ioj) is flown between two curves
            item["kind"] == "roll" and item["marker"] == "_" and loops and loops[-1][1] and after_arc
        ):
            after_arc = False
    return loops


def test_catalogue_has_the_embedded_roll_codes_under_test():
    assert set(EMBEDDED_ROLL_FIGURES) == set(ROLL_ARCS)


@pytest.mark.parametrize("code", sorted(ROLL_ARCS))
def test_loop_carrying_the_roll_matches_open_aero(code):
    arcs, carrier, plan = ROLL_ARCS[code]
    open_aero = _merged_open_aero_loops(plan)
    figure = OlanFig.take([code])[0]
    loops = [el for el in figure.fig.oels if el.kind == "Loop"]

    # the same loops in the same order, and the roll on the same one
    assert [abs(amount) / 360 for amount, _ in open_aero] == [
        abs(el.loopamount) for el in loops
    ]
    assert [carries for _, carries in open_aero] == [el.canRoll for el in loops]


@pytest.mark.parametrize("code", sorted(ROLL_ARCS))
def test_open_aero_arc_and_pyolan_loop_have_one_apex(code):
    arcs, carrier, plan = ROLL_ARCS[code]
    # OpenAero's e! arc starts after the arcs before it; the path is level at each
    # multiple of 180 degrees from the start of the figure
    before = sum(arcs[:carrier])
    low, high = sorted((before, before + arcs[carrier]))
    open_aero_apex = [k for k in range(-4, 5) if low < 180 * k < high]

    figure = OlanFig.take([code])[0]
    rolls = figure.element_rolls()
    loops = figure.loop_amounts(rolls)
    angles, canopies = figure.path_angles(loops, rolls)
    index = next(
        i for i, el in enumerate(figure.fig.oels) if el.kind == "Loop" and el.canRoll
    )
    pyolan_apex = horizontal_fractions(angles[index], loops[index] * canopies[index])

    assert len(open_aero_apex) == 1
    assert len(pyolan_apex) == 1
