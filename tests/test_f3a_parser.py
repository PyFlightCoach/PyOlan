"""F3A catalogue description parser (pyolan.f3a).

The metadata checks compare the f3a builder's template of each parsed figure
with the USG drawing metadata in tests/data/f3a/usg_drawings.json (scraped from
the drawing PDFs by scripts/scrape_usg_drawings.py): entry and exit attitude,
entry and exit height, and whether the figure reverses the direction of flight
(turnaround) or not (centre). Only the families implemented so far are checked.
"""

import json
from pathlib import Path

import geometry as g
import numpy as np
import pytest
import schemas.positioning as p
from flightdata import State
from tuning.builders import load_builder

from pyolan.f3a import F3AParseError, parse_f3a_description
from pyolan.f3a.normalise import normalise, normalise_number, split_description
from pyolan.f3a.rolls import parse_roll

FIXTURE = json.loads(
    (Path(__file__).parent / "data" / "f3a" / "usg_drawings.json").read_text()
)
IMPLEMENTED_GROUPS = ("01", "06", "22", "26")

# The template's lines all take the builder's line_length, so a figure N with
# a 45 degree line does not close: it exits at mid height.
OPEN_FIGURE_N = {"26.5", "26.6", "26.7", "26.8"}


# ---------------------------------------------------------------- normalising


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1¼ snap-roll", "1 1/4 snap roll"),
        ("11/4 snap roll", "1 1/4 snap roll"),  # rulebook PDF artefact
        ("½ roll", "1/2 roll"),
        ("45° Knife Edge down-line", "45 degree knife-edge downline"),
        ("2/4pt roll", "2/4-point roll"),
        ("4 point roll", "4-point roll"),
        ("legs 1&3", "legs 1 & 3"),
        ("Square loop on corner from top , inverted entry", "square loop on corner from top, inverted entry"),
    ],
)
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_split_description_number_and_k():
    desc = split_description("1.9 Knife-edge loop from top  (K6)")
    assert (desc.number, desc.k, desc.text) == ("01.9", 6, "knife-edge loop from top")


def test_split_description_repeated_k_must_agree():
    assert split_description("Loop (K5) (K5)").k == 5
    with pytest.raises(F3AParseError, match="conflicting K"):
        split_description("Loop (K5) (K6)")


def test_split_description_number_must_match():
    with pytest.raises(F3AParseError, match="does not match"):
        split_description("01.9 Loop (K5)", number="01.8")


def test_normalise_number():
    assert normalise_number("1.9") == "01.9"
    assert normalise_number("q.7") == "Q.7"


# ---------------------------------------------------------------- rolls


@pytest.mark.parametrize(
    "phrase, kinds, turns",
    [
        ("half roll", "r", [0.5]),
        ("full roll", "r", [1]),
        ("one roll", "r", [1]),
        ("2 rolls", "r", [2]),
        ("1/4 roll", "r", [0.25]),
        ("8-point roll", "rrrrrrrr", [0.125] * 8),
        ("2/4-point roll", "rr", [0.25, 0.25]),
        ("snap roll", "s", [1]),
        ("1 1/4 snap roll", "s", [1.25]),
        ("1 1/2 snap", "s", [1.5]),
        ("three consecutive 1/4 rolls", "rrr", [0.25] * 3),
    ],
)
def test_parse_roll(phrase, kinds, turns):
    roll = parse_roll(phrase)
    assert "".join(r.pfc_char for r in roll.roll_arr) == kinds
    assert roll.turns() == turns


def test_negative_snap():
    roll = parse_roll("1 negative snap")
    assert roll.roll_arr[0].negative and roll.roll_arr[0].kind == "snap"


def test_not_a_roll():
    assert parse_roll("stall turn") is None


# ---------------------------------------------------------------- strictness


@pytest.mark.parametrize(
    "text, words",
    [
        ("Square loop on corner with half rolls in legs 1 & 3 and a banana", "banana"),
        ("Rolling circle with one roll sideways", "sideways"),
        ("Figure N. Vertical upline from upright, 1/4 roll, cartwheel, exit upright", "cartwheel"),
        ("Loop with full roll at bottom", "at bottom"),
    ],
)
def test_unknown_words_are_named(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


def test_geometric_contradiction_is_an_error():
    # a 45 degree line cannot follow a 1/4 loop from a vertical line
    with pytest.raises(F3AParseError):
        parse_f3a_description(
            "Figure X. Vertical upline from upright, 1/4 pushed loop, 45° downline, exit upright"
        )


# ---------------------------------------------------------------- figures


def test_knife_edge_loop_links_the_mirror_image():
    fig = parse_f3a_description("01.7 Knife-edge loop (K6)")
    assert [e.kind for e in fig.elements] == ["roll", "loop", "roll"]
    assert fig.elements[1].kwargs["ke"] == pytest.approx(np.pi / 2)
    first, mirror = fig.ndmps["roll_option"]
    assert mirror == [-v for v in first]
    # the 1/4 rolls go back the way they came, so the exit is upright again
    assert first[0] == -first[2]


def test_rolling_circle_inside_rolls_with_the_turn():
    upright = parse_f3a_description("22.1 Rolling circle with one roll inside (K5)")
    inverted = parse_f3a_description("22.2 Rolling circle with one roll inside, inverted entry (K5)")
    outside = parse_f3a_description("22.3 Rolling circle with one roll outside (K5)")
    (turn, roll), _ = upright.ndmps["roll_option"]
    assert np.sign(turn) == np.sign(roll)
    (turn, roll), _ = outside.ndmps["roll_option"]
    assert np.sign(turn) == -np.sign(roll)
    # inverted, the yaw that turns right is negative but the roll is still right
    (turn, roll), _ = inverted.ndmps["roll_option"]
    assert np.sign(turn) == -np.sign(roll)


def test_square_loop_on_corner_half_rolls_push_the_following_corners():
    fig = parse_f3a_description(
        "06.3 Square loop on corner with half rolls in legs 1 & 3 (K4)"
    )
    loops = [e.args[0] for e in fig.elements if e.kind == "loop"]
    assert np.sign(loops).tolist() == [1, -1, -1, 1, 1]


def test_text_only_gives_position_from_the_shape():
    fig = parse_f3a_description("Square loop on corner (K3)")
    assert fig.info.position == p.Position.CENTRE
    assert fig.info.short_name == "f3a"
    assert fig.info.k == 3


# ---------------------------------------------------------------- fixture


@pytest.fixture(scope="module")
def mb():
    return load_builder("f3a")


def _height(z: float, zs: np.ndarray) -> str:
    low, high = zs.min(), zs.max()
    if high - low < 5:
        return "low"
    f = (z - low) / (high - low)
    return "low" if f < 0.25 else "high" if f > 0.75 else "middle"


def _template_metadata(fig, mb, entry: str) -> dict:
    mdef = mb.create_mdef(fig)
    if "roll_option" in mdef.mps.data:
        mdef.mps.data["roll_option"].defaul = 0
    orientation = p.Orientation.UPRIGHT if entry == "upright" else p.Orientation.INVERTED
    itrans = g.Transformation(g.Euler(orientation, 0, p.Heading.RTOL), g.P0())
    templates = mdef.create().create_template(itrans)
    tp = State.stack(templates, "element")
    body = State.stack(
        {k: v for k, v in templates.items() if k not in ("entry_line", "exit_line")},
        "element",
    )
    belly = tp.att.transform_point(g.PZ())
    nose = tp.att.transform_point(g.PX())
    zs = body.pos.z
    return dict(
        entry_attitude="upright" if belly.z[0] < 0 else "inverted",
        exit_attitude="upright" if belly.z[-1] < 0 else "inverted",
        entry_height=_height(zs[0], zs),
        exit_height=_height(zs[-1], zs),
        kind="turnaround" if nose.x[0] * nose.x[-1] < 0 else "centre",
    )


def _cases():
    for entry in FIXTURE:
        if entry["group"] not in IMPLEMENTED_GROUPS:
            continue
        marks = []
        if entry["number"] in OPEN_FIGURE_N:
            marks.append(pytest.mark.xfail(strict=True, reason="figure N line lengths are not linked"))
        yield pytest.param(entry, id=entry["number"], marks=marks)


@pytest.mark.parametrize("entry", _cases())
def test_matches_usg_drawing(entry, mb):
    fig = parse_f3a_description(entry["description"], entry["number"], entry["k"])
    assert fig.info.k == entry["k"]
    assert fig.info.short_name == entry["number"]
    position = p.Position.CENTRE if entry["kind"] == "centre" else p.Position.END
    assert fig.info.position == position
    keys = ("entry_attitude", "exit_attitude", "entry_height", "exit_height", "kind")
    expected = {k: entry[k] for k in keys}
    assert _template_metadata(fig, mb, entry["entry_attitude"]) == expected
