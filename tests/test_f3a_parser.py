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
from schemas import aresti as a
from tuning.builders import load_builder

from pyolan.f3a import F3AParseError, parse_f3a_description
from pyolan.f3a.normalise import normalise, normalise_number, split_description
from pyolan.f3a.rolls import parse_roll

FIXTURE = json.loads(
    (Path(__file__).parent / "data" / "f3a" / "usg_drawings.json").read_text()
)
FIXTURE_BY_NUMBER = {entry["number"]: entry for entry in FIXTURE}
# one group per line; add a group here when its family is implemented
IMPLEMENTED_GROUPS = tuple(
    (Path(__file__).parent / "data" / "f3a" / "implemented_groups.txt").read_text().split()
)

# The template's lines all take the builder's line_length, so a figure N with
# a 45 degree line does not close: it exits at mid height. Decided 2026-11-18:
# line lengths are left to scoring and the layout, not tied by the parser.
OPEN_FIGURE_N = {"26.5", "26.6", "26.7", "26.8"}
# The drawings put the entry of a cobra roll from top at "middle" height (the V
# descends to low). The template measures heights against the figure's own
# range, so the entry of a V is "high". Open question for the user.
OPEN_COBRA_FROM_TOP = {f"08.{n}" for n in range(5, 11)}


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
        ("1 positive snap", "s", [1]),
        ("2/4-point rolls", "rr", [0.25, 0.25]),
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
    assert [e.kind for e in fig.elements] == ["roll", "loop", "line", "roll"]
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


def test_rolling_loop_roll_is_integrated_through_the_whole_loop():
    (loop,) = parse_f3a_description("01.1 Rolling loop with one roll (from bottom) (K5)").elements
    assert loop.kwargs["rollangle"] == pytest.approx(2 * np.pi)
    (loop,) = parse_f3a_description("01.3 Loop with 8-point roll (from bottom) (K5)").elements
    assert loop.kwargs["rollangle"] == pytest.approx(np.pi / 2)
    assert loop.kwargs["rollposition"] == pytest.approx(0.5)


def test_open_loop_direction_gives_an_option_drawn_first():
    fig = parse_f3a_description(FIXTURE_BY_NUMBER["26.1"]["description"], "26.1")
    assert isinstance(fig, a.Option)
    drawn, other = fig.figures
    # the 1/8 knife-edge loop after the stall turn yaws the other way
    assert drawn.ndmps["roll_option"][0][1] == -other.ndmps["roll_option"][0][1]
    assert drawn.ndmps["roll_option"][0][0] == other.ndmps["roll_option"][0][0]


def test_stated_loop_direction_gives_one_figure():
    fig = parse_f3a_description(FIXTURE_BY_NUMBER["26.5"]["description"], "26.5")
    assert isinstance(fig, a.Figure)


def _kinds(text: str) -> list[str]:
    return [e.kind for e in parse_f3a_description(text).elements]


def test_two_loops_put_the_rolls_at_the_far_point_of_each_loop():
    fig = parse_f3a_description("02.5 Two loops with full roll first top, half roll second (from bottom) (K4)")
    first, second = fig.elements
    assert first.kwargs["rolls"] != second.kwargs["rolls"]
    with pytest.raises(F3AParseError, match="at bottom"):
        parse_f3a_description("Two loops with half rolls at bottom (K3)")


def test_snap_sign_is_parsed_but_the_builder_cannot_carry_it():
    # an unstated sign is either; a stated one is checked for spelling only,
    # because the builder's snap has no positive or negative flavour
    for text in ("1 negative snap", "1 positive snap", "snap"):
        loop = parse_f3a_description(f"Avalanche with {text} (from top)").elements[0]
        assert loop.kwargs["rolltypes"] == "snap"


def test_triangular_loop_roll_placement():
    # apex start: a lone roll goes on the base, plural rolls on all three legs
    assert _kinds("Triangular loop with full roll (from bottom)") == [
        "loop", "line", "loop", "roll", "loop", "line", "loop"
    ]
    assert _kinds("Triangular loop with 1/2 rolls (from bottom)").count("roll") == 3
    # base start: the sloping legs
    assert _kinds("Triangular loop (base at bottom) with half rolls in 45 degree legs") == [
        "loop", "roll", "loop", "roll", "loop"
    ]
    with pytest.raises(F3AParseError, match="base is at the top"):
        parse_f3a_description("Triangular loop with full roll at bottom (from bottom)")


def test_square_loop_exit_roll_follows_a_line_and_ends_the_figure():
    kinds = _kinds("Square loop with half rolls (K5)")
    assert kinds == ["loop", "roll", "loop", "roll", "loop", "roll", "loop", "line", "roll"]
    assert not parse_f3a_description("Square loop with half rolls").elements[-1].kwargs["padded"]
    assert _kinds("Square loop with full snap over top").count("roll") == 1


def _loop_turns(text: str) -> list[float]:
    fig = parse_f3a_description(text)
    return [round(float(e.args[0]) / (2 * np.pi), 3) for e in fig.elements if e.kind == "loop"]


def test_cuban_eight_has_a_roll_on_each_45_degree_line():
    for text in (
        "Cuban eight with 2/4pt rolls",
        "Reverse cuban eight (from bottom) with full rolls",
        "Cuban eight from top with half rolls",
    ):
        assert _kinds(text) == ["loop", "roll", "loop", "roll", "loop"]
    # without rolls the 45 degree lines are plain lines
    assert _kinds("Cuban eight") == ["loop", "line", "loop", "line", "loop"]


def test_cuban_eight_loop_amounts_and_order():
    # 5/8 loop, 3/4 loop the other way, 1/8 loop; reversed for the reverse figure
    assert _loop_turns("Cuban eight with full rolls") == [0.625, -0.75, 0.125]
    assert _loop_turns("Reverse cuban eight (from bottom) with full rolls") == [0.125, -0.75, 0.625]
    # from top is the mirror image
    assert _loop_turns("Cuban eight from top with full rolls") == [-0.625, 0.75, -0.125]


def test_cuban_eight_half_rolls_give_inside_loops_and_full_rolls_an_outside_one():
    # half rolls invert the second loop, so it is pulled; a full roll leaves it pushed
    assert _loop_turns("Cuban eight with 2/4pt rolls")[1] > 0
    assert _loop_turns("Cuban eight with full rolls")[1] < 0


def test_knife_edge_cuban_eight_has_quarter_rolls_on_entry_and_exit():
    kinds = _kinds("Knife-edge Cuban eight")
    assert kinds[0] == kinds[-1] == "roll" and kinds.count("loop") == 3
    assert _kinds("Knife-edge Cuban eight with full rolls").count("roll") == 4


def test_cuban_eight_rolls_must_be_plural_and_known():
    with pytest.raises(F3AParseError, match="full roll"):
        parse_f3a_description("Cuban eight with full roll")
    with pytest.raises(F3AParseError, match="banana"):
        parse_f3a_description("Cuban eight with full rolls, banana")


def _leg_lengths(fig, mb) -> list[float]:
    """Path length of each run of non-loop elements between loops (entry and exit lines excluded)."""
    mdef = mb.create_mdef(fig)
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    legs: list[float] = []
    previous_loop = True
    for name, st in templates.items():
        if name in ("entry_line", "exit_line"):
            continue
        index = int(name.split("_")[1])
        length = float(np.sum(np.linalg.norm(np.diff(st.pos.data, axis=0), axis=1)))
        if fig.elements[index].kind == "loop":
            previous_loop = True
            continue
        if previous_loop:
            legs.append(0.0)
        previous_loop = False
        legs[-1] += length
    return legs


@pytest.mark.parametrize(
    "text, sloping",
    [
        ("Triangular loop with full roll (from bottom)", (0, 2)),
        ("Triangular loop with 1/2 rolls (from bottom)", (0, 2)),
        ("Triangular loop (base at bottom) with half rolls in 45 degree legs", (0, 1)),
        ("Triangular loop from top (base at top) with 2/4pt rolls in 45 degree legs", (0, 1)),
    ],
)
def test_triangle_45_degree_legs_are_the_same_length(text, sloping, mb):
    legs = _leg_lengths(parse_f3a_description(text), mb)
    assert legs[sloping[0]] == pytest.approx(legs[sloping[1]])


def test_six_sided_loop_is_six_equal_sixth_loops():
    fig = parse_f3a_description("07.1 Six sided loop (K4)")
    assert [e.kind for e in fig.elements] == ["loop", "line"] * 5 + ["loop"]
    assert [e.args[0] for e in fig.elements if e.kind == "loop"] == pytest.approx([np.pi / 3] * 6)
    from_top = parse_f3a_description("07.3 Six sided loop from top (K4)")
    assert [e.args[0] for e in from_top.elements if e.kind == "loop"] == pytest.approx([-np.pi / 3] * 6)
    with pytest.raises(F3AParseError, match="half rolls"):
        parse_f3a_description("Six sided loop with half rolls")


def test_cobra_roll_puts_one_roll_in_each_45_degree_leg():
    assert _kinds("08.1 Cobra roll with 2/4pt rolls (K3)") == [
        "loop", "roll", "loop", "roll", "loop"
    ]
    loops = [e.args[0] for e in parse_f3a_description("Cobra roll with 2/2pt rolls").elements if e.kind == "loop"]
    assert np.sign(loops).tolist() == [1, -1, 1]
    # a half roll leaves the apex inverted, so the apex is flown the same way as
    # the corners (all pulled from bottom, all pushed from top)
    for text, sign in (("Cobra roll with half rolls", 1), ("Cobra roll from top with half rolls", -1)):
        loops = [e.args[0] for e in parse_f3a_description(text).elements if e.kind == "loop"]
        assert np.sign(loops).tolist() == [sign] * 3
    with pytest.raises(F3AParseError, match="plural"):
        parse_f3a_description("Cobra roll with half roll")


def test_golf_ball_shape_and_roll_placement():
    plain = _kinds("09.1 Golf ball (45 degrees up, 3/4 inside loop, 45 degrees down, pull to level), (K3)")
    assert plain == ["loop", "line", "loop", "line", "loop"]
    fig = parse_f3a_description("09.5 Golf ball with 2/4pt rolls (K3)")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "roll", "loop"]
    with pytest.raises(F3AParseError, match="outside loop"):
        parse_f3a_description("Golf ball (45 degrees up, 3/4 outside loop, 45 degrees down, pull to level)")
    with pytest.raises(F3AParseError, match="inverted entry"):
        parse_f3a_description(
            "Golf ball (45 degrees up, 3/4 inside loop, 45 degrees down, pull to level), inverted entry"
        )


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
            marks.append(pytest.mark.xfail(strict=True, reason="figure N line lengths are left to scoring and layout"))
        if entry["number"] in OPEN_COBRA_FROM_TOP:
            marks.append(pytest.mark.xfail(strict=True, reason="cobra roll from top: drawing entry height is middle, template says high"))
        yield pytest.param(entry, id=entry["number"], marks=marks)


@pytest.mark.parametrize("entry", _cases())
def test_matches_usg_drawing(entry, mb):
    parsed = parse_f3a_description(entry["description"], entry["number"], entry["k"])
    figures = parsed.figures if isinstance(parsed, a.Option) else [parsed]
    keys = ("entry_attitude", "exit_attitude", "entry_height", "exit_height", "kind")
    expected = {k: entry[k] for k in keys}
    position = p.Position.CENTRE if entry["kind"] == "centre" else p.Position.END
    for fig in figures:
        assert fig.info.k == entry["k"]
        assert fig.info.short_name == entry["number"]
        assert fig.info.position == position
        assert _template_metadata(fig, mb, entry["entry_attitude"]) == expected
