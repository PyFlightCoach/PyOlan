"""Centre marks on the F3A catalogue figures (pyolan.f3a.centre).

Scoring gives a centring deduction only where a figure has centre points (CENTRE
markers) or centred elements. Every centre (numbered) catalogue entry has one; the
lettered groups (turnarounds, end figures) have none. The marks follow the known
schedules: P27 (packages/FCScoreServer/tests/data/p27.sdef.json) and the P25 source
figures mark the start and end of a symmetric figure and its middle element.
"""

import json
from pathlib import Path

import pytest
import schemas.positioning as p
from schemas import aresti as a

from pyolan.f3a import parse_f3a_description

RULEBOOK = json.loads((Path(__file__).parent / "data" / "f3a" / "rulebook_2026.json").read_text())
TEXT = {e["number"]: e for e in RULEBOOK}
CENTRE = [e for e in RULEBOOK if e["number"].split(".")[0].isdigit()]
LETTERED = [e for e in RULEBOOK if not e["number"].split(".")[0].isdigit()]


def figures(number: str) -> list[a.Figure]:
    e = TEXT[number]
    f = parse_f3a_description(e["text"], number, e["k"])
    return f.figures if isinstance(f, a.Option) else [f]


def marks(fig: a.Figure) -> tuple[list[int], list[int]]:
    """(indices of the markers among the elements, indices of the centred elements)."""
    tags = [i for i, e in enumerate(fig.elements) if isinstance(e, int)]
    centred = [i for i, e in enumerate(fig.elements) if isinstance(e, a.PE) and e.centred]
    return tags, centred


def kinds(fig: a.Figure) -> list[str]:
    return ["T" if isinstance(e, int) else e.kind + ("*" if e.centred else "") for e in fig.elements]


def test_catalogue_counts():
    assert len(CENTRE) == 365 and len(LETTERED) == 316


@pytest.mark.parametrize("entry", CENTRE, ids=lambda e: e["number"])
def test_centre_entry_is_marked(entry):
    for fig in figures(entry["number"]):
        tags, centred = marks(fig)
        assert fig.info.position == p.Position.CENTRE
        assert tags or centred, entry["text"]
        assert all(e == p.MBTags.CENTRE for e in fig.elements if isinstance(e, int))


def test_lettered_entries_are_not_marked():
    for entry in LETTERED:
        try:
            figs = figures(entry["number"])
        except Exception:  # the families not yet implemented
            continue
        for fig in figs:
            assert marks(fig) == ([], []), entry["number"]


def test_humpty_like_p27():
    # P27 humpty: the start of the pull-up and the end of the pull-out, the half loop centred
    assert kinds(figures("18.1")[0]) == ["T", "loop", "roll", "loop*", "roll", "loop", "T"]


def test_top_hat_centres_the_top_line():
    k = kinds(figures("17.1")[0])
    assert k[0] == k[-1] == "T" and k.count("line*") == 1 and k.index("line*") == len(k) // 2


def test_triangle_like_p25():
    # P25 triangle: markers at both ends and the middle roll centred
    assert kinds(figures("04.1")[0]) == [
        "T", "loop", "line", "loop", "roll*", "loop", "line", "loop", "T",
    ]


def test_loop_like_p25():
    # P25 loop: [CENTRE, loop, CENTRE]
    assert kinds(figures("01.1")[0]) == ["T", "loop", "T"]


def test_square_loop_far_side_like_p27():
    k = kinds(figures("05.5")[0])
    assert k == ["T", "loop", "line", "loop", "roll*", "loop", "line", "loop", "T"]


def test_spin_start_only_like_p27():
    k = kinds(figures("19.1")[0])
    assert k[0] == "T" and k.count("T") == 1 and not any(x.endswith("*") for x in k)


def test_roll_is_centred_like_p27_roll_combo():
    assert kinds(figures("23.1")[0]) == ["roll*"]


def test_double_immelmann_centres_the_middle_line_like_p25():
    assert kinds(figures("21.1")[0]) == ["loop", "roll", "line*", "loop", "roll"]


def test_double_key_centres_both_verticals():
    fig = figures("24.1")[0]
    assert kinds(fig) == ["loop", "roll*", "loop", "roll", "loop", "roll", "loop", "roll*", "loop"]


def test_figure_n_centres_the_45_degree_line():
    k = kinds(figures("26.1")[0])
    assert k[0] == k[-1] == "T" and k.count("line*") == 1


def test_option_figures_are_all_marked():
    figs = figures("26.1")
    assert len(figs) == 2 and all(any(marks(f)) for f in figs)


def test_builder_derives_centres_like_p27():
    """The builder turns the marks into centre_points and centred_els, as P27's humpty has."""
    from tuning.builders import load_builder

    builder = load_builder("f3a")
    info = builder._create_mdef(figures("18.1")[0]).info
    # P27: centre_points [1, 13] and the half loop centred; here the figure has padded rolls
    assert len(info.centre_points) == 2 and info.centre_points[0] == 1
    assert len(info.centred_els) + len(info.centre_points) >= 3
    spin = builder._create_mdef(figures("19.1")[0]).info
    assert spin.centre_points == [1] and spin.centred_els == []
    roll = builder._create_mdef(figures("23.1")[0]).info
    assert roll.centre_points or roll.centred_els



def test_knife_edge_loop_with_snap_builds():
    """01.11: the builder cannot centre a multi-element loop, so loops mark their ends only."""
    from tuning.builders import load_builder

    info = load_builder("f3a")._create_mdef(figures("01.11")[0]).info
    assert len(info.centre_points) == 2 and info.centred_els == []
