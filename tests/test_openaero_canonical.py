"""Unit tests of the canonical form used by the OpenAero differential tests.

The OpenAero side is checked on hand-made buildShape traces in the format
tools/openaero/oa-trace.js records, the PyOlan side on hand-made elements.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
from schemas import aresti as a

sys.path.insert(0, str(Path(__file__).parent))
from openaero import canonical as C  # noqa: E402

pytestmark = pytest.mark.unit


def t(shape, params, att0=0):
    return {"shape": shape, "params": params, "att0": att0, "dir0": 0, "att1": att0, "dir1": 0}


def line(n=4, *extra):
    return t("Line", [n, *extra])


def roll(extent, stops=0, top=False, corr=False):
    return t("Roll", [extent, stops, top, False, corr, "", False])


# ---------------------------------------------------------------------------
# OpenAero traces


def test_entry_and_exit_lines_without_rolls_are_dropped():
    trace = [line(4, "entry"), t("Corner", 45), line(), t("Corner", -45), line(2, "exit")]
    assert C.oa_canonical(trace) == [["arc", 45, []], ["line", []], ["arc", -45, []]]


def test_roll_gap_placeholders_are_not_lines():
    # roll1-gap0 lines of zero length separate the parts of a point roll
    trace = [line(4), roll(90), t("Line", [0, "roll1-gap0"]), roll(90), line(4)]
    assert C.oa_canonical(trace) == [["line", [["roll", 180, 1]]]]


def test_point_roll_pieces_merge_and_opposite_rolls_do_not():
    trace = [line(), roll(180), line(1), roll(-180), line()]
    assert C.oa_canonical(trace) == [["line", [["roll", 180, 1], ["roll", 180, -1]]]]


def test_roll_in_the_top_is_embedded_in_the_loop():
    # o(1): a loop with a full roll at the top, drawn as two curves
    trace = [t("Curve", 180), roll(360, top=True), t("Curve", 180)]
    assert C.oa_canonical(trace) == [["arc", 360, [["roll", 360, 1]]]]


def test_an_inverting_roll_in_a_loop_flips_openaero_pull_sign():
    # OpenAero signs the curve after a half roll in the top as a push
    trace = [t("Curve", 135), roll(180, top=True), t("Curve", -135)]
    assert C.oa_canonical(trace) == [["arc", 270, [["roll", 180, 1]]]]


def test_a_correction_roll_in_the_top_is_embedded_in_the_loop():
    """OpenAero builds the correction roll with params[2] false even in the top of a
    loop (o-); the RollTopLine split tells where the top is."""
    top = [t("Curve", 135), t("RollTopLine", ""), t("Curve", 45)]
    after = [t("Curve", -45), t("Curve", -135)]
    assert C.oa_canonical(top + [roll(-180, corr=True)] + after) == [["arc", 360, [["roll", 180, 1]]]]
    # outside the top a correction roll stays on its line
    assert C.oa_canonical([t("Curve", 180), line(), roll(-180, corr=True), line(), t("Curve", -180)]) == [
        ["arc", 180, []], ["line", [["roll", 180, 1]]], ["arc", -180, []],
    ]


def test_split_loops_merge_into_one_arc():
    trace = [t("Curve", 90), t("Curve", 90), line(), t("Corner", 90)]
    assert C.oa_canonical(trace) == [["arc", 180, []], ["line", []], ["arc", 90, []]]


def test_spin_entry_snaps_and_negative_flags():
    # iv1s with a snap after it: Corner -90, Line, Spin, Snap(neg), Line, Corner
    trace = [
        line(), t("Corner", -90), line(), t("Spin", [360, 0, False, ""]),
        t("Snap", [-180, 1, False, ""]), line(), t("Corner", -90), line(),
    ]
    assert C.oa_canonical(trace) == [
        ["arc", -90, []], ["line", [["spin", 360, 1], ["snap", 180, -1]]], ["arc", -90, []],
    ]
    assert C.oa_negatives(trace) == [["spin", False], ["snap", True]]


def test_correction_rolls_are_reported():
    trace = [t("Curve", 225), roll(180, corr=True), t("Corner", 45)]
    assert C.oa_corrections(trace) == [180]
    assert C.oa_canonical(trace)[1] == ["line", [["roll", 180, 1]]]


def test_stall_turn_and_tailslides():
    trace = [t("Corner", 90), line(), t("Hammer", 12), line(), t("Corner", 90)]
    assert C.oa_canonical(trace)[2] == ["stall"]
    assert C.oa_tokens([t("Tailslide", "T")]) == [["tail", -1]]
    assert C.oa_tokens([t("Tailslide", "t")]) == [["tail", 1]]


@pytest.mark.parametrize(
    "draw, attitude, expected",
    [
        ("j2", 0, ["turn", 180, []]),
        ("j11", 0, ["turn", 90, [["roll", 360, 1]]]),  # 1j1: inwards
        ("J11", 0, ["turn", 90, [["roll", 360, -1]]]),  # 1jo1: outwards
        ("J11", 180, ["turn", 90, [["roll", 360, 1]]]),  # -1j1-: inwards when inverted
        ("j215", 0, ["turn", 180, [["roll", 540, 1]]]),  # 2j15: a roll and a half
        ("jio215", 0, ["turn", 180, [["roll", 360, 1], ["roll", 180, -1]]]),
        ("j33", 0, ["turn", 270, [["roll", 1080, 1]]]),
    ],
)
def test_turn_draw_strings(draw, attitude, expected):
    assert C.oa_tokens([t("Turn", draw, att0=attitude)]) == [expected]


# ---------------------------------------------------------------------------
# PyOlan elements


def test_elements_loop_with_roll_and_lines():
    pes = [a.line(), a.loop(np.pi / 2), a.roll([np.pi / 2, np.pi / 2], rolltypes="rr"), a.loop(-np.pi / 2), a.line()]
    assert C.py_canonical(pes) == [["arc", 90, []], ["line", [["roll", 180, 1]]], ["arc", -90, []]]


def test_elements_point_roll_string():
    assert C.py_canonical([a.roll("2x4", rolltypes="roll", padded=False)]) == [["line", [["roll", 180, 1]]]]
    assert C.py_canonical([a.roll("2x-4", rolltypes="roll")]) == [["line", [["roll", 180, 1]]]]


def test_elements_mixed_roll_types():
    pes = [a.roll([np.pi, -2 * np.pi], rolltypes="rs")]
    assert C.py_canonical(pes) == [["line", [["roll", 180, 1], ["snap", 360, -1]]]]


def test_elements_spin_replaces_the_arc_before_it():
    pes = [a.spin(2 * np.pi), a.line(), a.loop(-np.pi / 2)]
    assert C.py_canonical(pes) == [["arc", None, []], ["line", [["spin", 360, 1]]], ["arc", -90, []]]
    # the wildcard arc matches OpenAero's -90 corner
    assert C.segments_equal(
        [["arc", -90, []], ["line", [["spin", 360, 1]]], ["arc", -90, []]],
        C.py_canonical(pes),
    )


def test_elements_loop_with_embedded_roll():
    pes = [a.loop(2 * np.pi, rolls=np.pi, rolltypes="roll")]
    assert C.py_canonical(pes) == [["arc", 360, [["roll", 180, 1]]]]


def test_elements_plain_turn_drops_the_bank_rolls():
    bank, ke, unbank = np.radians(60), np.radians(30), np.radians(-60)
    pes = [a.roll([bank], padded=False), a.loop(np.pi / 2, ke=ke), a.roll([unbank], padded=False)]
    assert C.py_canonical(pes) == [["turn", 90, []]]


def test_elements_rolling_turn_signs_are_relative_to_the_turn():
    inwards = [a.loop(np.pi / 2, rolls=2 * np.pi, ke=np.pi / 2)]
    outwards = [a.loop(-np.pi / 2, rolls=2 * np.pi, ke=np.pi / 2)]
    assert C.py_canonical(inwards) == [["turn", 90, [["roll", 360, 1]]]]
    assert C.py_canonical(outwards) == [["turn", 90, [["roll", 360, -1]]]]


def test_elements_stallturn_and_tailslide():
    pes = [a.loop(np.pi / 2), a.line(), a.stallturn(), a.line(), a.loop(np.pi / 2)]
    assert C.py_canonical(pes)[2] == ["stall"]
    assert C.py_canonical([a.tailslide(-1)]) == [["tail", -1]]


def test_segments_equal_compares_everything_but_wildcard_arcs():
    assert C.segments_equal([["arc", None, []]], [["arc", 45, []]])
    assert not C.segments_equal([["arc", 45, []]], [["arc", -45, []]])
    assert not C.segments_equal([["line", [["roll", 360, 1]]]], [["line", []]])
    assert not C.segments_equal([["stall"]], [["stall"], ["line", []]])
