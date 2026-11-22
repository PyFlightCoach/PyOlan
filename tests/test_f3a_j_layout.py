"""F3A group J as an Option through the sequence layout (J cross-box, owner decision 2026-11-22).

The drawings draw the top line of J.1-J.33 and the bottom line of J.38-J.41 obliquely
(cross-box). Each such entry is an Option: member 1 the in-plane top hat (it sizes the figure),
member 2 the cross-box one, which the layout takes as a depth correction (``prepare.
is_depth_correction``): it copies the planar sizes, shares the planar exit and joins from an
approach offset in Y. The parse and template checks of every entry are in test_f3a_parser.py;
these run the layout and the height derivation on a few of them.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import schemas.positioning as p
from flightanalysis.layout import layout_sequence
from flightanalysis.layout.heights import figure_heights, heights_source
from flightanalysis.layout.prepare import is_depth_correction, make_problems
from schemas import ManInfo
from schemas import aresti as a
from schemas.aresti import Figure, Sequence, line
from tuning.builders import load_builder, load_layout

from pyolan.f3a import parse_f3a_description

RULEBOOK = {
    e["number"]: f"{e['number']} {e['text']}"
    for e in json.loads((Path(__file__).parent / "data" / "f3a" / "rulebook_2026.json").read_text())
}
# a top hat from the bottom (J.1), from top (J.11), with a three-stop roll (J.17) and a spin entry (J.38)
ENTRIES = ["J.1", "J.11", "J.17", "J.38"]


@pytest.fixture(scope="module")
def f3a():
    return load_builder("f3a"), load_layout("f3a")


def neighbour():
    return Figure(
        info=ManInfo.build(
            "neighbour", "neighbour", 1, p.Position.CENTRE,
            p.boxlocationmaker(None, None, p.Orientation.UPRIGHT), p.boxlocationmaker(),
        ),
        elements=[line(length=80)], ndmps={},
    )


def sequence(*figures):
    return Sequence(name="j", rules="f3a", figures=list(figures))


@pytest.mark.parametrize("number", ENTRIES)
def test_the_layout_marks_the_cross_box_member_as_a_depth_correction(f3a, number):
    builder, settings = f3a
    option = parse_f3a_description(RULEBOOK[number])
    assert isinstance(option, a.Option)
    problems = make_problems(sequence(option, neighbour()), builder, settings, "builder", None, p.Heading.LTOR)
    assert problems[0].cross_box == (False, True)
    assert [is_depth_correction(problems[0], i, builder.box) for i in (0, 1)] == [False, True]
    assert not is_depth_correction(problems[1], 0, builder.box)  # a single figure is never one


@pytest.mark.parametrize("wind", [p.Heading.LTOR, p.Heading.RTOL])
@pytest.mark.parametrize("order", ["first", "last"])
@pytest.mark.parametrize("number", ENTRIES)
def test_a_sequence_with_a_j_entry_lays_out_and_the_correction_shares_the_exit(f3a, number, order, wind):
    builder, settings = f3a
    option = parse_f3a_description(RULEBOOK[number])
    figures = [option, neighbour()] if order == "first" else [neighbour(), option]
    index = figures.index(option)
    result = layout_sequence(sequence(*figures), builder, settings, start="builder", wind=wind)

    assert result.success, (result.report["errors"], result.report["violations"])
    assert not any("exit misses" in str(item) for item in (*result.report["errors"], *result.warnings))
    planar, correction = result.placements[index].options
    # the planar member sizes the figure in the plane; the correction joins from an offset in Y
    assert planar.depth_shift == pytest.approx(0, abs=1e-6)
    assert abs(correction.depth_shift) > 50
    np.testing.assert_allclose(planar.geometry.exit.pos.data, correction.geometry.exit.pos.data, atol=1e-6)
    assert correction.wall_breaches["front"] == correction.wall_breaches["back"] == 0
    assert [o["depth_correction"] for o in result.report["figures"][index]["options"]] == [False, True]
    for template in result.templates[index]:
        assert template.pos.y[-1] == pytest.approx(planar.geometry.exit.pos.y[0], abs=0.5)  # back on the plane


def test_heights_are_derived_for_the_planar_member_including_non_level_pairs_and_the_layout_reads_them(f3a):
    # derive_heights runs each member alone: the planar one gets its pairs (the only set the
    # layout reads: it sizes the figure); the correction cannot exit on the plane alone
    builder, settings = f3a
    planar, correction = parse_f3a_description(RULEBOOK["J.1"]).figures
    pairs = figure_heights(planar, builder, settings)
    # the lines are free (owner 2026-11-22), so the top hat need not finish at its entry height:
    # BM and MB are pairs as well as BB and MM
    found = {(pair.entry, pair.exit) for pair in pairs}
    assert found >= {(p.Height.BTM, p.Height.BTM), (p.Height.MID, p.Height.MID),
                     (p.Height.BTM, p.Height.MID), (p.Height.MID, p.Height.BTM)}
    stored = a.Option(figures=[
        planar.model_copy(update={"heights": pairs, "heights_source": heights_source(planar, builder, settings)}),
        correction.model_copy(update={"heights": [], "heights_source": heights_source(correction, builder, settings)}),
    ])
    result = layout_sequence(sequence(stored, neighbour()), builder, settings, start="builder")
    assert result.success, (result.report["errors"], result.report["violations"])
    placement = result.placements[0]
    assert (placement.entry_level, placement.exit_level) == (0, 0)
