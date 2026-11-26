"""Elements from OpenAero's drawing strings (drawn.py, plan Phase D)."""

import sys
from pathlib import Path

import pytest

from pyolan.drawn import elements_from_draw
from pyolan.figure_parser import OlanFig
from pyolan.primitives import OlanEl, li, lo, st, ts

sys.path.insert(0, str(Path(__file__).parent))
from openaero import canonical as C  # noqa: E402

pytestmark = pytest.mark.component

NOLINE = OlanEl("Line", 0, False)


@pytest.mark.parametrize(
    "draw, oels, slots",
    [
        # 45 degree line: entry and exit lines without a slot are dropped
        ("~d~_~D~", [lo(1 / 8), li(), lo(-1 / 8)], [None, 0, None]),
        # square loop: lines without a slot between loops are unjudged lines
        ("~~~v~~v~_~v~~v~~~", [lo(1 / 4), NOLINE, lo(1 / 4), li(), lo(1 / 4), NOLINE, lo(1 / 4)],
         [None, None, None, 0, None, None, None]),
        # reversing loop: same-sign curves are one loop, the roll in its top
        ("~_v=m!_V=_~", [li(), lo(3 / 4, True), lo(-1 / 4), li()], [0, 1, None, 2]),
        ("~_v=M!_V=_~", [li(), lo(1 / 4), lo(-3 / 4, True), li()], [0, None, 1, 2]),
        # vertical eights: a change of sign is a new loop
        ("~mOm~", [lo(1 / 2), lo(-1), lo(1 / 2)], [None, None, None]),
        ("~o«O»~", [lo(1), lo(-1)], [None, None]),
        # stall turn and tailslides, an inverted entry mark
        ("-~V~_~H~_''V~", [lo(-1 / 4), li(), st(), li(), lo(-1 / 4)], [None, 0, None, 1, None]),
        ("~~v''_''~t~~_''v~~", [lo(1 / 4), li(), ts(1), li(), lo(1 / 4)], [None, 0, None, 1, None]),
        ("~~v''_''~T~~_''v~~", [lo(1 / 4), li(), ts(-1), li(), lo(1 / 4)], [None, 0, None, 1, None]),
    ],
)
def test_elements_from_draw(draw, oels, slots):
    assert elements_from_draw(draw) == (oels, slots)


@pytest.mark.parametrize("draw", ["~j1~", "~v~_~u~_''v~", "~''v=4p!_~", "~_~_~"])
def test_what_is_not_drawn_keeps_the_primitive(draw):
    """Turns, point tips, the clover's quarter rolls and two slots on one line."""
    assert elements_from_draw(draw) is None


@pytest.mark.parametrize(
    "olan, arcs",
    [
        # OpenAero's arcs (canonical form, consecutive arcs merged) from the corpora
        # F8: inverted variants and after stall turns
        ("-24ipp8", [90, -90]),
        ("-ikz-", [90, 135, 135]),
        ("-dhd-", [-45, -45, -45, -45]),
        # F9: with no roll, the attitude marker selects the variant
        ("d-", [45, 135]),
        ("id-", [-45, -135]),
    ],
)
def test_figures_follow_openaero_drawing(olan, arcs):
    fig = OlanFig.take([olan])[0]
    assert fig.drawn_slots is not None
    assert [s[1] for s in C.py_canonical(fig.create_elements()) if s[0] == "arc"] == arcs


def test_turns_and_legacy_codes_keep_their_primitive():
    for olan in ["2j", "1jo1", "1xm(1)1", "xa", "oj"]:
        assert OlanFig.take([olan])[0].drawn_slots is None


@pytest.mark.parametrize(
    "olan, where",
    [("o(2)", "in brackets"), ("2v", "before the figure"), ("24h(2)4", "in brackets")],
)
def test_a_roll_openaero_ignores_is_reported(olan, where):
    fig = OlanFig.take([olan])[0]
    assert any(w.startswith("OpenAero ignores the roll") and where in w for w in fig.warnings)


def test_rolls_in_their_slots_are_not_reported():
    for olan in ["o1", "hp(1)", "2b2", "24h4"]:
        assert not [w for w in OlanFig.take([olan])[0].warnings if "ignores" in w]
