"""parse_olan places each figure at its position in the sequence (A2).

The sequences link (D2): each figure starts in the attitude the one before ends in.
"""

from dataclasses import replace

import pytest
from flightanalysis.elements.tags import DGTags
from flightanalysis.scoring.downgrade import DownGrades
from pyolan.parser import parse_olan
from tuning.builders import load_builder


@pytest.fixture(scope="module")
def probe_builder():
    """IMAC builder with probe downgrades that only look at the sequence ends."""
    b = load_builder("IMAC", category="unlimited")
    base = b.dgs["track_z"]
    return replace(
        b,
        dgs=DownGrades([
            replace(base, name="on_start", tags=DGTags.parse("SEQSTART", "LINE", "")),
            replace(base, name="on_end", tags=DGTags.parse("", "LINE", "SEQEND")),
        ]),
    )


def applied(fig):
    return {adg.name for adg in fig.definition.dgs}


def test_first_and_last_figures_are_placed_in_both_figure_and_definition(probe_builder):
    figs = parse_olan("1a2 1 1a2", probe_builder)

    assert len(figs) == 3
    assert [f.aresti.info.sequence_position for f in figs] == ["first", None, "last"]
    assert [f.definition.info.sequence_position for f in figs] == ["first", None, "last"]
    exit_id = len(figs[0].definition.eds) - 1
    assert applied(figs[0]) == {"on_start_0"}
    assert applied(figs[1]) == set()
    assert applied(figs[2]) == {f"on_end_{exit_id}"}


def test_a_single_figure_is_both_first_and_last(probe_builder):
    (fig,) = parse_olan("1a2", probe_builder)

    assert fig.aresti.info.sequence_position == "only"
    assert fig.definition.info.sequence_position == "only"
    assert {n.split("_")[0] for n in applied(fig)} == {"on"}
    assert len(applied(fig)) == 2


def test_f3a_figures_keep_no_position():
    f3a = load_builder("f3a")

    figs = parse_olan("1a2 1", f3a)

    assert [f.aresti.info.sequence_position for f in figs] == [None, None]
    assert [f.definition.info.sequence_position for f in figs] == [None, None]
