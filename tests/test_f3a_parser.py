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

# The template's 45 degree line takes the builder's line_length and the verticals a
# fixed 130 m (a start value for the layout), so a figure N with a 45 degree line does
# not close in the template: it exits at mid height. Decided 2026-11-18: line lengths are
# left to scoring and the layout, not tied by the parser; 2026-11-20 (A4 review): the
# layout may choose each vertical's length, which the parser makes possible (see the
# figure N test below).
OPEN_FIGURE_N = {"26.5", "26.6", "26.7", "26.8"}
# A cobra roll from top is a V: its entry height is "middle" in the drawings but
# can be middle or high depending on the manoeuvre before it (decided
# 2026-11-18), and the template measures heights against the figure's own range.
# Entry and exit heights are not compared for these.
FLEXIBLE_START_HEIGHT = {f"08.{n}" for n in range(5, 11)}
# The USG text layer gives 14.21 "Height : low->low" but its drawing (like 14.22's,
# whose description is the same words) has the entry and exit at the waist of
# the knife-edge eight, "middle entry and exit": a typo in the USG metadata.
FIXTURE_HEIGHT_TYPO = {"14.21": "middle"}
# E.63 "Figure 9 from middle inverted with ..., exit upright": the USG metadata says
# "Attitude : upright->upright" but its drawing has the entry line dashed (inverted)
# and the exit solid, as the description says: a typo in the USG metadata.
FIXTURE_ATTITUDE_TYPO = {"E.63": ("inverted", "upright")}
# F.63 "Half reverse cuban eight from top inverted with ..., exit upright": the USG
# metadata says "Attitude : inverted->high" (the exit attitude is a height word, see
# usg-drawings-crosscheck.md); the description and the drawing say exit upright.
FIXTURE_ATTITUDE_TYPO["F.63"] = ("inverted", "upright")
# what the fixture records for the entries above (asserted, so a corrected fixture
# shows up here)
FIXTURE_ATTITUDE_RECORDED = {"E.63": ("upright", "upright"), "F.63": ("inverted", "high")}
# The 45 degree line of a half Cuban eight is one loop radius long, but a roll on it
# (with its pads) is longer than that at the builder's default radius of 55 m (a
# 2/2pt roll is 180 m), so the line grows and the figure ends below (above, from top)
# where it starts instead of one box higher. The layout has to raise the radius until
# the roll fits (decided as for the Cuban eight); these entries are checked at 150 m,
# where the roll fits and the heights are as drawn.
HALF_CUBAN_LAYOUT_RADIUS = {
    f"F.{n}" for n in (*range(3, 9), *range(15, 20), *range(23, 29), *range(35, 41), *range(49, 65))
}


# Group K (45 degree lines either side of a half loop): the figure now finishes at its
# entry height (decided 2026-11-20, see the K tests below), but the template measures
# heights against its own range, with roll lines that grow with their rolls and
# knife-edge options whose loop leaves the figure's range either side, so the USG
# "low->low" is not compared against the template's height words for these.
K_HEIGHTS_OPEN = {f"K.{n}" for n in range(1, 33)}


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
    assert [e.kind for e in fig.elements] == ["roll", "line", "loop", "line", "roll"]
    assert fig.elements[2].kwargs["ke"] == pytest.approx(np.pi / 2)
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


@pytest.mark.parametrize("number", ["26.1", "26.4", "26.5", "26.8"])
def test_figure_n_verticals_have_lengths_of_their_own(number):
    # decided 2026-11-20 (A4 review: "free the lengths so that some pair works"): each padded
    # roll on a vertical line has a numeric line_length, which the layout makes a variable of
    # its own (pe.<index>.line_length) that is not compared with the other lines. The 45 degree
    # line keeps the figure's line_length (and its snap roll, in 26.5-26.8, none of its own).
    parsed = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number)
    figures = parsed.figures if isinstance(parsed, a.Option) else [parsed]
    for fig in figures:
        rolls = [e for e in fig.elements if e.kind == "roll"]
        free = [e for e in rolls if "line_length" in e.kwargs]
        assert all(e.kwargs["line_length"] == 130.0 for e in free)
        if number in ("26.1", "26.4"):
            # up, (45 degree line), up with a half roll, down: three rolled verticals
            assert len(free) == len(rolls) == 3
            assert [e.kind for e in fig.elements].count("line") == 1  # the 45 degree line
        else:
            # full roll up, snap on the 45 degree line, 1 1/4 snap up, 1/4 roll down
            assert len(rolls) == 4 and len(free) == 3
            (diagonal,) = [e for e in rolls if "line_length" not in e.kwargs]
            assert diagonal.kwargs["rolltypes"] == "snap"
        assert "line_length" not in fig.ndmps


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


def test_six_sided_loop_has_45_degree_lines():
    # corners 1/8, 1/4, 1/8, 1/8, 1/4, 1/8 give lines at 45, 135, 180, 225 and 315 degrees
    turns = [1 / 8, 1 / 4, 1 / 8, 1 / 8, 1 / 4, 1 / 8]
    fig = parse_f3a_description("07.1 Six sided loop (K4)")
    assert [e.kind for e in fig.elements] == ["loop", "line"] * 5 + ["loop"]
    assert [e.args[0] for e in fig.elements if e.kind == "loop"] == pytest.approx(
        [2 * np.pi * t for t in turns]
    )
    from_top = parse_f3a_description("07.3 Six sided loop from top (K4)")
    assert [e.args[0] for e in from_top.elements if e.kind == "loop"] == pytest.approx(
        [-2 * np.pi * t for t in turns]
    )
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


def test_rolls_that_start_or_end_a_figure_have_a_line_to_the_next_element():
    # F3A: a line between the roll and its neighbouring loop; the lines share a
    # comparison parameter of 20 m that need not match the figure's other lines
    fig = parse_f3a_description("01.7 Knife-edge loop (K6)")
    assert [e.kind for e in fig.elements] == ["roll", "line", "loop", "line", "roll"]
    assert [e.kwargs.get("length") for e in fig.elements if e.kind == "line"] == ["roll_line_length"] * 2
    assert fig.ndmps["roll_line_length"].value == 20
    assert fig.ndmps["roll_line_length"].like == "line_length"
    # a figure with no such roll does not get the parameter
    assert "roll_line_length" not in parse_f3a_description("Loop (K2)").ndmps


@pytest.mark.parametrize(
    "text, radius",
    [
        ("Cuban eight", 55),
        ("Cuban eight with full rolls", 55),
        ("Cuban eight from top with half rolls", 55),
        ("Reverse cuban eight with full rolls", 55),
        ("Knife-edge Cuban eight", 55),
        # the roll and its pads are longer than two radii at the default radius
        ("Cuban eight with 2/4pt rolls", 70),
        ("Reverse cuban eight from top with 2/4pt rolls", 70),
    ],
)
def test_cuban_eight_finishes_at_its_entry_height(text, radius, mb):
    mdef = mb.create_mdef(parse_f3a_description(text))
    mdef.mps.data["loop_radius"].defaul = radius
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = 0
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    tp = State.stack(templates, "element")
    assert tp.pos.z[-1] - tp.pos.z[0] == pytest.approx(0, abs=1e-6)


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


def _template_metadata(fig, mb, entry: str, radius: float | None = None) -> dict:
    mdef = mb.create_mdef(fig)
    if radius is not None:
        mdef.mps.data["loop_radius"].defaul = radius
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = 0
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
        # implemented_groups.txt lists whole groups ("19") or single entries ("E.12")
        if entry["group"] not in IMPLEMENTED_GROUPS and entry["number"] not in IMPLEMENTED_GROUPS:
            continue
        marks = []
        if entry["number"] in OPEN_FIGURE_N:
            marks.append(pytest.mark.xfail(strict=True, reason="figure N line lengths are left to scoring and layout"))
        yield pytest.param(entry, id=entry["number"], marks=marks)


@pytest.mark.parametrize("entry", list(_cases()))
def test_matches_usg_drawing(entry, mb):
    parsed = parse_f3a_description(entry["description"], entry["number"], entry["k"])
    figures = parsed.figures if isinstance(parsed, a.Option) else [parsed]
    keys = ("entry_attitude", "exit_attitude", "entry_height", "exit_height", "kind")
    expected = {k: entry[k] for k in keys}
    if entry["number"] in FLEXIBLE_START_HEIGHT:
        expected["entry_height"] = expected["exit_height"] = "high"
        assert entry["entry_height"] == entry["exit_height"] == "middle"
    entry_attitude = entry["entry_attitude"]
    if entry["number"] in FIXTURE_ATTITUDE_TYPO:
        assert (entry["entry_attitude"], entry["exit_attitude"]) == FIXTURE_ATTITUDE_RECORDED[entry["number"]]
        entry_attitude, expected["exit_attitude"] = FIXTURE_ATTITUDE_TYPO[entry["number"]]
        expected["entry_attitude"] = entry_attitude
    if entry["number"] in FIXTURE_HEIGHT_TYPO:
        assert entry["entry_height"] == entry["exit_height"] == "low"
        expected["entry_height"] = expected["exit_height"] = FIXTURE_HEIGHT_TYPO[entry["number"]]
    if entry["number"] in K_HEIGHTS_OPEN:
        for key in ("entry_height", "exit_height"):
            expected.pop(key)
    position = p.Position.CENTRE if entry["kind"] == "centre" else p.Position.END
    for fig in figures:
        assert fig.info.k == entry["k"]
        assert fig.info.short_name == entry["number"]
        assert fig.info.position == position
        radius = 150.0 if entry["number"] in HALF_CUBAN_LAYOUT_RADIUS else None
        got = _template_metadata(fig, mb, entry_attitude, radius)
        assert {key: value for key, value in got.items() if key in expected} == expected


# ---------------------------------------------------------------- groups 11 and 12


def _rolls_of(fig):
    return [e for e in fig.elements if e.kind == "roll"]


def test_two_reversed_point_rolls_are_one_roll_with_opposite_stops():
    fig = parse_f3a_description("11.5 45 degree down with two 2/4 pt rolls reversed (K4)")
    (roll,) = _rolls_of(fig)
    quarter = np.pi / 2
    assert roll.args[0] == pytest.approx([quarter, quarter, -quarter, -quarter])
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop"]


def test_forty_five_degree_up_and_down_mirror_each_other():
    up = parse_f3a_description("11.11 45 degree up with full snap roll (K3)")
    down = parse_f3a_description("11.1 45 degree down with full snap roll (K3)")
    assert [e.args[0] for e in up.elements if e.kind == "loop"] == pytest.approx([np.pi / 4, -np.pi / 4])
    assert [e.args[0] for e in down.elements if e.kind == "loop"] == pytest.approx([-np.pi / 4, np.pi / 4])


def test_figure_z_has_two_3_8_loops_in_opposite_senses_and_a_centred_roll():
    # the half roll turns the pilot over between the loops, so both are pulled
    # (inverted entry: both pushed); from top the loops go down instead
    def loops(text):
        fig = parse_f3a_description(text)
        assert [e.kind for e in fig.elements] == ["loop", "roll", "loop"]
        return [e.args[0] for e in fig.elements if e.kind == "loop"]

    three_eighths = 3 * np.pi / 4
    assert loops("12.1 Figure Z with half roll up (K3)") == pytest.approx([three_eighths] * 2)
    assert loops("12.2 Figure Z with half roll up, inverted entry (K3)") == pytest.approx(
        [-three_eighths] * 2
    )
    assert loops("12.5 Figure Z with 2/2pt roll up (K4)") == pytest.approx(
        [three_eighths, -three_eighths]
    )
    assert loops("12.7 Figure Z from top with half roll down (K3)") == pytest.approx(
        [-three_eighths] * 2
    )


def test_figure_z_roll_direction_word_must_match_the_start():
    with pytest.raises(F3AParseError, match="not up"):
        parse_f3a_description("Figure Z from top with half roll up (K3)")
    with pytest.raises(F3AParseError, match="not down"):
        parse_f3a_description("Figure Z with half roll down (K3)")
    # the word may be missing, as in 12.11
    parse_f3a_description("Figure Z from top with 2/2pt roll (K4)")


def test_forty_five_degree_line_rejects_unknown_words():
    with pytest.raises(F3AParseError):
        parse_f3a_description("45 degree down with full snap roll sideways (K3)")
    with pytest.raises(F3AParseError):
        parse_f3a_description("45 degree down with three 2/4 pt rolls reversed (K3)")


# ---------------------------------------------------------------- groups 13 and 14


def test_start_at_the_middle_is_only_accepted_by_the_families_that_use_it():
    for text in (
        "Loop from middle",
        "Loop (top entry)",
        "Cuban eight (middle entry, top first)",
        "Hourglass (from bottom) (top first)",
    ):
        with pytest.raises(F3AParseError):
            parse_f3a_description(text)
    # both spellings of a start at the middle
    parse_f3a_description("Vertical eight (from middle)")
    parse_f3a_description("Vertical knife-edge eight, middle entry and exit, top first")
    with pytest.raises(F3AParseError, match="top or bottom goes first"):
        parse_f3a_description("Hourglass (middle entry)")


def test_hourglass_corners_and_roll_placement():
    # four 3/8 corners, 45 degree lines up and down with the same roll on both
    assert _loop_turns("13.1 Hourglass (K4)") == [0.375, -0.375, -0.375, 0.375]
    assert _loop_turns("13.19 Hourglass (top entry) (K4)") == [-0.375, 0.375, 0.375, -0.375]
    assert _kinds("Hourglass") == ["loop", "line", "loop", "line", "loop", "line", "loop"]
    assert _kinds("Hourglass with half rolls up and down") == [
        "loop", "roll", "loop", "line", "loop", "roll", "loop"
    ]
    # from the middle: one roll, on the long diagonal
    assert _kinds("Hourglass (middle entry, top first) half roll down") == [
        "loop", "line", "loop", "line", "loop", "roll", "loop", "line", "loop", "line", "loop"
    ]
    assert _loop_turns("Hourglass (middle entry, top first)") == [0.125, 0.375, 0.375, -0.375, -0.375, -0.125]
    assert _loop_turns("Hourglass (middle entry, bottom first)") == [-0.125, -0.375, -0.375, 0.375, 0.375, 0.125]
    with pytest.raises(F3AParseError, match="down line"):
        parse_f3a_description("Hourglass (middle entry, top first) half roll up")
    with pytest.raises(F3AParseError, match="rolls up and down"):
        parse_f3a_description("Hourglass with half roll up")


@pytest.mark.parametrize(
    "text",
    [
        "Hourglass (middle entry, top first)",
        "Hourglass (middle entry, top first) 2/4pt roll down",
        "Hourglass (middle entry, bottom first) half roll up",
        "Hourglass (middle entry, bottom first) 2/4pt roll up",
        "Vertical eight (from middle) with half roll",
        "Vertical eight (from bottom) with half rolls",
    ],
)
def test_middle_entry_figures_cross_at_the_entry_height(text, mb):
    # finishes at its entry height, and the figure is as far above it as below it
    # (the long diagonal of an hourglass runs through the entry height)
    mdef = mb.create_mdef(parse_f3a_description(text))
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = 0
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    z = State.stack(templates, "element").pos.z
    assert z[-1] - z[0] == pytest.approx(0, abs=1e-6)
    if "middle" in text:
        assert z.max() - z[0] == pytest.approx(z[0] - z.min(), abs=1e-6)


def test_vertical_eight_loops_and_waist_rolls():
    assert _loop_turns("14.1 Vertical eight (from bottom) (K3)") == [0.5, -1, 0.5]
    assert _loop_turns("14.11 Vertical eight (from top) (K3)") == [-0.5, 1, -0.5]
    assert _loop_turns("14.7 Vertical eight (from middle) (K3)") == [1, -1]
    assert _kinds("Vertical knife-edge eight, middle entry and exit, top first").count("loop") == 2
    assert _kinds("Vertical eight (from bottom)") == ["loop", "loop", "loop"]
    with pytest.raises(F3AParseError, match="one crossing"):
        parse_f3a_description("Vertical eight (from middle) with half rolls")


def _rolled_pieces(text: str) -> tuple[list[str], list[int]]:
    elements = parse_f3a_description(text).elements
    return (
        [e.kind for e in elements],
        [i for i, e in enumerate(elements) if "rolls" in e.kwargs],
    )


def test_hourglass_top_line_is_shorter_than_the_45_degree_legs():
    # decided 2026-11-18: the top line need not match the 45 degree legs
    top = "(0.7071067811865476*(line_length-(2*loop_radius)))"
    fig = parse_f3a_description("Hourglass")
    assert [e.kwargs.get("length") for e in fig.elements if e.kind == "line"] == [None, top, None]
    fig = parse_f3a_description("Hourglass (middle entry, top first)")
    assert [e.kwargs.get("length") for e in fig.elements if e.kind == "line"].count(top) == 2


def test_vertical_eight_waist_roll_is_integrated_into_the_loops():
    # half of the roll in the last 1/8 of the loop before the waist and half in the
    # first 1/8 of the loop after it (decided 2026-11-18): 3/8 | 1/8r 1/8r | 3/4 | 1/8r 1/8r | 3/8
    kinds, rolled = _rolled_pieces("Vertical eight (from bottom) with half rolls")
    assert kinds == ["loop"] * 7 and rolled == [1, 2, 4, 5]
    kinds, rolled = _rolled_pieces("Vertical eight (from top) with half roll after first half loop")
    assert kinds == ["loop"] * 5 and rolled == [1, 2]
    kinds, rolled = _rolled_pieces("Vertical eight (from middle) with half roll")
    assert kinds == ["loop"] * 4 and rolled == [1, 2]
    kinds, rolled = _rolled_pieces("Vertical Knife-edge eight with two half roll")
    assert kinds == ["roll", "line"] + ["loop"] * 7 + ["line", "roll"] and rolled == [3, 4, 6, 7]
    # both pieces of a roll go the same way: linked in the mirror option. The pieces
    # that start on the knife-edge also link their yaw angle (an eighth of a turn).
    fig = parse_f3a_description("Vertical eight (from bottom) with half rolls")
    first, mirror = fig.ndmps["roll_option"]
    assert mirror == [-v for v in first]
    refs = [int(fig.elements[i].kwargs["rolls"].split("[")[1][:-1]) for i in (1, 2, 4, 5)]
    assert [first[n] for n in refs] == pytest.approx([np.pi / 2] * 4)


def test_vertical_knife_edge_eight_is_flown_in_knife_edge():
    fig = parse_f3a_description("14.17 Vertical knife-edge eight (K6)")
    assert [e.kind for e in fig.elements] == ["roll", "line", "loop", "loop", "loop", "line", "roll"]
    assert all(e.kwargs["ke"] == pytest.approx(np.pi / 2) for e in fig.elements if e.kind == "loop")


# ---------------------------------------------------------------- groups 17 and 18


def _closure(text: str, mb, **params) -> float:
    mdef = mb.create_mdef(parse_f3a_description(text))
    for key, value in params.items():
        mdef.mps.data[key].defaul = value
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = 0
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    z = State.stack(templates, "element").pos.z
    return float(z[-1] - z[0])


def test_top_hat_has_a_roll_centred_on_each_vertical_line():
    for text in ("Top hat with 2/4pt rolls", "Top hat from top with 2/2pt rolls, inverted entry"):
        assert _kinds(text) == ["loop", "roll", "loop", "line", "loop", "roll", "loop"]
    # up, over, down: the two corners at the top turn the other way to the others
    elements = parse_f3a_description("Top hat with 2/2pt rolls").elements
    first, second, third, fourth = (np.sign(e.args[0]) for e in elements if e.kind == "loop")
    assert second == third == -first == -fourth
    # a single roll phrase leaves a vertical line without one
    with pytest.raises(F3AParseError, match="both vertical lines"):
        parse_f3a_description("Top hat with half roll")


def test_humpty_bump_is_a_quarter_half_quarter_loop_with_a_roll_on_each_vertical_line():
    assert _kinds("Humpty bump, half roll up, 2/4pt roll down") == ["loop", "roll", "loop", "roll", "loop"]
    for text in (
        "Humpty bump, half roll up, 2/4pt roll down",
        "Humpty bump from top, half roll down, 2/4pt roll up, inverted entry",
    ):
        assert sorted(abs(t) for t in _loop_turns(text)) == [0.25, 0.25, 0.5]
    # "up" and "down" name the lines, and the order they are given in does not matter
    first = parse_f3a_description("Humpty bump, half roll up, full snap down").elements
    swapped = parse_f3a_description("Humpty bump, full snap down, half roll up").elements
    assert [e.kwargs.get("rolls") for e in first] == [e.kwargs.get("rolls") for e in swapped]
    # from the top the down line comes first
    top = parse_f3a_description("Humpty bump from top, half roll down, full snap up").elements
    assert [e.kwargs.get("rolls") for e in top] == [e.kwargs.get("rolls") for e in first]
    for text in (
        "Humpty bump, half roll up",
        "Humpty bump, half roll up, half roll up",
        "Humpty bump, half roll, full roll",
    ):
        with pytest.raises(F3AParseError, match="roll up and a roll down|unexpected"):
            parse_f3a_description(text)


@pytest.mark.parametrize(
    "text, params",
    [
        ("Top hat with 2/4pt rolls", {}),
        ("Top hat from top with 2/2pt rolls", {}),
        ("Humpty bump, half roll up, 2/4pt roll down", {}),
        ("Humpty bump from top, 2/4pt roll down, full roll up", {}),
    ],
)
def test_top_hat_and_humpty_bump_finish_at_their_entry_height(text, params, mb):
    assert _closure(text, mb, **params) == pytest.approx(0, abs=1e-6)


def test_humpty_bump_with_a_snap_finishes_a_little_below_its_entry(mb):
    # Builder inconsistency, not tied by the parser: the pads of a snap line are
    # sized for a 15 m snap but the snap flies 17.6 m, so the down line is 2.6 m
    # longer than the up line (the figure still closes to well within the box).
    assert abs(_closure("Humpty bump, 2/4pt roll up, full snap down", mb)) == pytest.approx(2.557, abs=0.01)


# ---------------------------------------------------------------- groups 15 and 16


def test_square_eights_corners_and_waist_rolls():
    def turns(text):
        return [e.args[0] / (2 * np.pi) for e in parse_f3a_description(text).elements if e.kind == "loop"]

    # signs are relative to the aircraft, so only the sizes are checked here
    assert [abs(t) for t in turns("Square horizontal eight")] == [0.25] * 8
    assert [abs(t) for t in turns("Square vertical eight (from bottom)")] == [0.25] * 8
    # half rolls are on both passes of the waist (legs 2 and 6), not in the loops
    kinds, _ = _rolled_pieces("Square vertical eight (from top) with half rolls")
    assert [i for i, k in enumerate(kinds) if k == "roll"] == [3, 11]
    # from the middle one roll goes on the line between the squares
    kinds, _ = _rolled_pieces("Square vertical eight (from middle) with half roll")
    assert [i for i, k in enumerate(kinds) if k == "roll"] == [7]
    for text in (
        "Square vertical eight (from bottom) with half roll",
        "Square vertical eight (from middle) with half rolls",
        "Square horizontal eight with half rolls",
    ):
        with pytest.raises(F3AParseError, match="unexpected"):
            parse_f3a_description(text)


def test_figure_m_has_a_pushed_centre_half_loop_and_stall_turns():
    # the centre half loop is negative (a push) whatever the entry attitude; the
    # 1/4 loops that join the entry and exit lines are pulled upright, pushed inverted
    for text, corner in (
        ("Figure M with 3/4 rolls Centre half-loop is always flown negative (inverted)", 1),
        ("Figure M with 3/4 pt rolls", 1),
        ("Figure M with 3/4 rolls, inverted entry", -1),
    ):
        fig = parse_f3a_description(text)
        assert [e.kind for e in fig.elements].count("stallturn") == 2
        angles = [e.args[0] for e in fig.elements if e.kind == "loop"]
        assert angles == pytest.approx([corner * np.pi / 2, -np.pi, corner * np.pi / 2])
    with pytest.raises(F3AParseError, match="expected rolls on the up and the down"):
        parse_f3a_description("Figure M with 3/4 rolls up")


def test_figure_m_with_unequal_rolls_finishes_at_its_entry_height(mb):
    assert _closure("Figure M with 3/4pt rolls up, 1/4 rolls down", mb) == pytest.approx(0, abs=1e-6)
    assert _closure("Figure M with 3/4 rolls", mb) == pytest.approx(0, abs=1e-6)


def test_figure_m_verticals_are_flown_either_way_independently(mb):
    fig = parse_f3a_description("Figure M with 3/4 rolls")
    assert {k for k in fig.ndmps if k.startswith("roll_option")} == {"roll_option", "roll_option_2"}
    for name in ("roll_option", "roll_option_2"):
        first, mirror = fig.ndmps[name]
        assert len(first) == 2 and mirror == [-v for v in first]
    refs = []
    for pe in fig.elements:
        for value in pe.args:
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and item.startswith("roll_option"):
                    refs.append(item)
    assert sorted(refs) == ["roll_option[0]", "roll_option[1]", "roll_option_2[0]", "roll_option_2[1]"]
    mb.create_mdef(fig)


@pytest.mark.parametrize("choice", [(0, 0), (1, 0), (0, 1), (1, 1)])
@pytest.mark.parametrize("text", ["Figure M with 3/4 rolls", "Figure M with 3/4pt rolls up, 1/4 rolls down"])
def test_figure_m_either_direction_of_each_vertical_closes(text, choice, mb):
    mdef = mb.create_mdef(parse_f3a_description(text))
    for name, value in zip(("roll_option", "roll_option_2"), choice):
        mdef.mps.data[name].defaul = value
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    pos = State.stack(templates, "element").pos
    assert float(pos.z[-1] - pos.z[0]) == pytest.approx(0, abs=1e-6)
    assert float(pos.y[-1] - pos.y[0]) == pytest.approx(0, abs=1e-6)


# ---------------------------------------------------------------- group 21


def test_double_immelmann_is_a_roll_and_two_half_loops():
    fig = parse_f3a_description("21.1 Double Immelmann with half rolls (K3)")
    # the roll that starts the figure has a line after it, the second is on the line
    # between the half loops
    assert [e.kind for e in fig.elements] == ["roll", "line", "loop", "roll", "loop"]
    assert fig.elements[3].kwargs["padded"]
    assert _loop_turns("21.1 Double Immelmann with half rolls") == [-0.5, 0.5]


@pytest.mark.parametrize(
    "text, turns",
    [
        # a half roll makes the loop after it a pushed one (negative), a full roll
        # leaves it pulled; from top is the mirror image about the entry height
        ("Double Immelmann with half rolls", [-0.5, 0.5]),
        ("Double Immelmann with half roll first, full roll second", [-0.5, -0.5]),
        ("Double Immelmann with full rolls", [0.5, 0.5]),
        ("Double Immelmann with full rolls, inverted entry", [-0.5, -0.5]),
        ("Double Immelmann from top, half rolls", [0.5, -0.5]),
        ("Double Immelmann from top with full rolls", [-0.5, -0.5]),
    ],
)
def test_double_immelmann_pull_and_push(text, turns):
    assert _loop_turns(text) == turns


def test_double_immelmann_roll_first_and_second():
    fig = parse_f3a_description("21.3 Double Immelmann with half roll first, full roll second (K4)")
    first, second = fig.elements[0], fig.elements[3]
    assert (first.args[0], second.args[0]) == pytest.approx((np.pi, 2 * np.pi))
    fig = parse_f3a_description("21.5 Double Immelmann with full rolls (K3)")
    assert (fig.elements[0].args[0], fig.elements[3].args[0]) == pytest.approx((2 * np.pi, 2 * np.pi))


@pytest.mark.parametrize(
    "text",
    [
        "Double Immelmann",
        "Double Immelmann with half roll",
        "Double Immelmann with half roll first",
        "Double Immelmann with half rolls, full rolls",
        "Double Immelmann with half roll second, full roll first",
        "Double Immelmann with half rolls, banana",
        "Double Immelmann from middle, half rolls",
    ],
)
def test_double_immelmann_rejects_unclear_rolls(text):
    with pytest.raises(F3AParseError):
        parse_f3a_description(text)


@pytest.mark.parametrize(
    "text",
    [
        "Double Immelmann with half rolls",
        "Double Immelmann with half roll first, full roll second, inverted entry",
        "Double Immelmann with full rolls",
        "Double Immelmann from top, half rolls",
        "Double Immelmann from top, half roll first, full roll second",
        "Double Immelmann from top with full rolls, inverted entry",
    ],
)
def test_double_immelmann_finishes_at_its_entry_height(text, mb):
    mdef = mb.create_mdef(parse_f3a_description(text))
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    pos = State.stack(templates, "element").pos
    assert float(pos.z[-1] - pos.z[0]) == pytest.approx(0, abs=1e-6)


# ---------------------------------------------------------------- group 20


def _template_z(text: str, mb) -> np.ndarray:
    mdef = mb.create_mdef(parse_f3a_description(text))
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = 0
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    return np.asarray(State.stack(templates, "element").pos.z)


def test_stall_turn_has_a_centred_roll_on_each_line():
    fig = parse_f3a_description("Stall turn, 3/4 roll up, 1 1/4 snap roll down (K5)")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "stallturn", "roll", "loop"]
    assert [e.kwargs.get("rolltypes") for e in fig.elements if e.kind == "roll"] == ["roll", "snap"]
    assert all(e.kwargs["padded"] for e in fig.elements if e.kind == "roll")
    # the roll on the order of the words does not matter
    swapped = parse_f3a_description("Stall turn, 1 1/4 snap roll down, 3/4 roll up (K5)")
    assert [e.kind for e in swapped.elements] == [e.kind for e in fig.elements]


def test_stall_turn_without_commas_and_with_spaced_point_rolls():
    # the catalogue has "Stall turn 3/4 roll up" and "3/4 pt roll"
    fig = parse_f3a_description("20.3 Stall turn 3/4 roll up, 3/4 pt roll down, inverted exit (K3)")
    assert fig.info.short_name == "20.3"
    assert fig.info.end.orientation == p.Orientation.INVERTED


@pytest.mark.parametrize(
    "text, words",
    [
        ("Stall turn, 3/4 roll up", "roll up and a roll down"),
        ("Stall turn, 3/4 roll up, half roll up", "unexpected"),
        ("Stall turn, 3/4 roll up, half roll down, banana", "banana"),
        ("Stall turn, 3/4 roll", "unexpected"),
        ("Stall turn, 3/4 roll up, half roll down, inverted exit, exit inverted", "more than once|twice"),
        ("Stall turn from top, 3/4 roll up, half roll down", "no start height"),
    ],
)
def test_stall_turn_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


# whether the up and the down roll go the same way or opposite ways is decided by
# the exit attitude (the stall turn is a yaw about the belly axis), so the two are
# linked in the one mirror option; checked by brute force over steps._fly
@pytest.mark.parametrize(
    "number, same_way",
    [
        ("20.1", False), ("20.2", True), ("20.3", True),
        ("20.4", True), ("20.5", False), ("20.6", False),
        ("20.7", True), ("20.8", False), ("20.9", False),
    ],
)
def test_stall_turn_rolls_are_linked_by_the_exit_attitude(number, same_way):
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(entry["description"], number, entry["k"])
    assert isinstance(fig, a.Figure)
    assert set(k for k in fig.ndmps if k.startswith("roll_option")) == {"roll_option"}
    first, mirror = fig.ndmps["roll_option"]
    assert mirror == [-v for v in first]
    # every roll piece of both lines is in the option: up first, then down
    assert np.sign(first[0]) * np.sign(first[-1]) == (1 if same_way else -1)


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize(
    "text, tolerance",
    [
        ("Stall turn, 3/4 roll up, 3/4pt roll down", 1e-6),
        ("Stall turn, 3/4pt roll up, 3/4 roll down, inverted entry", 1e-6),
        # builder inconsistency, as the humpty bump: a snap's pads are sized for 15 m
        # but it flies 17.6 m, so the exit is 2.6 m low
        ("Stall turn, 3/4pt roll up, 1 1/4 snap roll down, inverted exit", 3.5),
    ],
)
def test_stall_turn_ends_as_far_below_the_entry_as_it_rises_above(text, tolerance, option, mb):
    # the drawings enter at the middle of the vertical and leave at its bottom
    mdef = mb.create_mdef(parse_f3a_description(text))
    mdef.mps.data["roll_option"].defaul = option
    entry = p.Orientation.INVERTED if "inverted entry" in text else p.Orientation.UPRIGHT
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(entry, 0, p.Heading.RTOL), g.P0())
    )
    z = np.asarray(State.stack(templates, "element").pos.z)
    assert float(z.max() - z[0]) > 0
    assert float(z.max() - z[0] - (z[0] - z[-1])) == pytest.approx(0, abs=tolerance)
    assert float(z[0] - z[-1]) > 0
    # centre figure: the exit continues the entry's way, at the same position
    pos = State.stack(templates, "element").pos
    assert float(pos.y[-1] - pos.y[0]) == pytest.approx(0, abs=1e-6)
    assert float(pos.x[-1] - pos.x[0]) < 0


def test_stall_turn_line_lengths_do_not_depend_on_the_rolls(mb):
    # the up line (loop excluded) is the same for every roll and the down line is
    # always twice the climb less the loop radius, so only the roll's pads differ
    heights = []
    for text in (
        "Stall turn, 3/4 roll up, 3/4pt roll down",
        "Stall turn, 3/4pt roll up, 1 1/4 snap roll down",
    ):
        z = _template_z(text, mb)
        heights.append(round(float(z.max() - z[-1]), 1))
    assert heights[0] == pytest.approx(heights[1], abs=3.0)


# ---------------------------------------------------------------- group 19: spins


def _fig19(number):
    entry = FIXTURE_BY_NUMBER[number]
    return parse_f3a_description(entry["description"], number, entry["k"])


@pytest.mark.parametrize(
    "number, kinds",
    [
        ("19.1", ["spin", "line", "loop"]),
        ("19.3", ["spin", "spin", "line", "loop"]),
        ("19.5", ["spin", "line", "loop"]),
        ("19.7", ["spin", "line", "loop", "line", "roll"]),
        ("19.9", ["spin", "line", "loop"]),
    ],
)
def test_spin_is_a_spin_a_downline_and_a_loop_out(number, kinds):
    fig = _fig19(number)
    assert [e.kind for e in fig.elements] == kinds
    # the spin drops from the entry line and the figure leaves the way it came
    assert fig.info.position == p.Position.CENTRE
    assert (fig.info.start.height, fig.info.end.height) == (p.Height.TOP, p.Height.BTM)


def test_spin_direction_is_the_builders_unless_it_is_tied_to_something():
    # a whole spin has no link, the pilot picks the direction
    assert not _fig19("19.1").ndmps
    assert _fig19("19.1").elements[0].args == [pytest.approx(5 * np.pi)]
    assert not [k for k in _fig19("19.5").ndmps if k.startswith("roll_option")]


@pytest.mark.parametrize(
    "text, exit_attitude",
    [
        ("2 1/2 turn spin", p.Orientation.INVERTED),  # a half turn leaves the canopy facing back
        ("2 1/2 turn spin, inverted entry", p.Orientation.UPRIGHT),
        ("Three turn spin", p.Orientation.UPRIGHT),
        ("Three turn spin, inverted entry", p.Orientation.INVERTED),
        ("2 turn opposite spin", p.Orientation.UPRIGHT),
    ],
)
def test_spin_exit_attitude_follows_from_the_turns(text, exit_attitude):
    assert parse_f3a_description(text).info.end.orientation == exit_attitude


def test_spin_stated_exit_attitude_must_be_the_flown_one():
    assert parse_f3a_description("2 1/2 turn spin, inverted exit")
    with pytest.raises(F3AParseError, match="exits inverted"):
        parse_f3a_description("2 1/2 turn spin, upright exit")
    with pytest.raises(F3AParseError, match="exits upright"):
        parse_f3a_description("Three turn spin, inverted exit")


def test_half_roll_exit_is_on_the_exit_line_with_the_line_before_a_final_roll():
    fig = _fig19("19.7")
    assert fig.elements[-1].kind == "roll"
    assert fig.elements[-1].kwargs["padded"] is False
    assert fig.elements[-2].kind == "line" and fig.elements[-2].kwargs == {"length": "roll_line_length"}
    assert "roll_line_length" in fig.ndmps
    # the half roll turns the loop's exit attitude round
    assert fig.info.end.orientation == p.Orientation.UPRIGHT


def test_opposite_spin_directions_are_linked_and_do_not_recover_in_between():
    fig = _fig19("19.3")
    first, second = fig.elements[0], fig.elements[1]
    assert first.kwargs == {"recovery_turns": 0.0}
    assert second.kwargs == {"nd_turns": 0.0}
    assert first.args == ["roll_option[0]"] and second.args == ["roll_option[1]"]
    option, mirror = fig.ndmps["roll_option"]
    assert option == [pytest.approx(4 * np.pi), pytest.approx(-4 * np.pi)]
    assert mirror == [-v for v in option]


@pytest.mark.parametrize(
    "number, entry, exit_, roll_with_spin",
    [
        ("19.9", p.Orientation.UPRIGHT, p.Orientation.UPRIGHT, True),
        ("19.10", p.Orientation.UPRIGHT, p.Orientation.INVERTED, False),
        ("19.11", p.Orientation.INVERTED, p.Orientation.UPRIGHT, True),
        ("19.12", p.Orientation.INVERTED, p.Orientation.INVERTED, False),
    ],
)
def test_spin_with_quarter_loop_and_roll_integrated_is_one_mirror_option(
    number, entry, exit_, roll_with_spin
):
    fig = _fig19(number)
    loop = fig.elements[2]
    assert fig.elements[0].args == ["roll_option[0]"]
    # the loop is in knife-edge, with the 1/4 roll spread over all of it
    assert loop.kwargs["ke"] == pytest.approx(np.pi / 2)
    assert loop.args == ["roll_option[1]"] and loop.kwargs["rolls"] == "roll_option[2]"
    assert "rollangle" not in loop.kwargs and "rollposition" not in loop.kwargs
    spin_turns, loop_angle, roll = fig.ndmps["roll_option"][0]
    assert spin_turns == pytest.approx(4.5 * np.pi)
    assert abs(loop_angle) == abs(roll) == pytest.approx(np.pi / 2)
    # the roll side against the loop side sets the exit attitude
    assert (np.sign(loop_angle) == np.sign(roll)) == (exit_ == p.Orientation.UPRIGHT)
    assert (fig.info.start.orientation, fig.info.end.orientation) == (entry, exit_)
    assert fig.ndmps["roll_option"][1] == [-v for v in fig.ndmps["roll_option"][0]]


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize("number", [f"19.{n}" for n in range(1, 13)])
def test_spin_figures_exit_in_the_stated_attitude_in_every_direction(number, option, mb):
    fig = _fig19(number)
    mdef = mb.create_mdef(fig)
    for name, mp in mdef.mps.data.items():
        if name.startswith("roll_option") or name.endswith("_turns"):
            mp.defaul = option
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(fig.info.start.orientation, 0, p.Heading.RTOL), g.P0())
    )
    states = State.stack(templates, "element")
    belly = states.att.transform_point(g.PZ()).z[-1]
    assert (belly > 0) == (fig.info.end.orientation == p.Orientation.INVERTED)
    # a centre figure: it leaves flying the way it came and without sideways drift
    assert states.att.transform_point(g.PX()).x[-1] * states.att.transform_point(g.PX()).x[0] > 0
    assert float(states.pos.y[-1] - states.pos.y[0]) == pytest.approx(0, abs=1e-6)
    # a spin always loses height
    assert float(states.pos.z[-1] - states.pos.z[0]) < 0


@pytest.mark.parametrize(
    "text, words",
    [
        ("2 1/4 turn spin", "1/4 loop"),
        ("2 1/4 turn spin, 1/4 loop with 1/4 roll integrated", "exit attitude"),
        ("2 1/4 turn spin, 1/4 loop with 1/4 roll integrated. Entry upright. Exit sideways", "unexpected"),
        ("2 1/2 turn spin, half roll exit, half roll exit", "unexpected"),
        ("Three turn spin, half roll exit", "unexpected"),
        ("Three turn spin, banana", "banana"),
        ("Three turn spin, inverted entry. Entry upright", "entry attitude"),
        ("Three turn spin, inverted exit, exit upright", "given twice"),
    ],
)
def test_spin_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


# ---------------------------------------------------------------- groups A (half square loop), C and D


def _acd_fig(number):
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(entry["description"], number, entry["k"])
    assert isinstance(fig, a.Figure)
    return fig


def _acd_states(fig, mb, option):
    mdef = mb.create_mdef(fig)
    for name, mp in mdef.mps.data.items():
        if name.startswith("roll_option"):
            mp.defaul = option
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(fig.info.start.orientation, 0, p.Heading.RTOL), g.P0())
    )
    return State.stack(templates, "element")


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize(
    "number", [f"A.{n}" for n in (*range(5, 11), *range(15, 31))] + ["C.3", "C.4"] + [f"D.{n}" for n in range(1, 13)]
)
def test_acd_figures_leave_in_the_stated_attitude_in_every_direction(number, option, mb):
    entry = FIXTURE_BY_NUMBER[number]
    states = _acd_states(_acd_fig(number), mb, option)
    belly = states.att.transform_point(g.PZ()).z
    assert ("inverted" if belly[0] > 0 else "upright") == entry["entry_attitude"]
    assert ("inverted" if belly[-1] > 0 else "upright") == entry["exit_attitude"]
    # a turnaround: it leaves flying the other way, in the entry's plane, at a different height
    nose = states.att.transform_point(g.PX()).x
    assert nose[0] * nose[-1] < 0
    assert float(states.pos.y[-1] - states.pos.y[0]) == pytest.approx(0, abs=1e-6)
    assert (float(states.pos.z[-1] - states.pos.z[0]) > 0) == (entry["exit_height"] == "high")


def test_acd_half_square_loop_roll_is_on_the_vertical_line():
    up = _acd_fig("A.5")
    assert [e.kind for e in up.elements] == ["loop", "roll", "loop"]
    assert up.elements[1].kwargs["padded"] is True
    assert up.elements[0].args[0] == pytest.approx(np.pi / 2)
    # a half roll makes the second corner a push, a full roll leaves it a pull
    assert up.elements[2].args[0] == pytest.approx(-np.pi / 2)
    assert _acd_fig("A.9").elements[2].args[0] == pytest.approx(np.pi / 2)
    assert _acd_fig("A.7").elements[1].args == ["2x2"]  # two half rolls
    assert _acd_fig("A.9").elements[1].args == [2 * np.pi]
    # from the top it is the mirror image: down first
    down = _acd_fig("A.15")
    assert [e.args[0] for e in down.elements if e.kind == "loop"] == pytest.approx([-np.pi / 2, np.pi / 2])
    assert [e.kind for e in _acd_fig("A.21").elements] == ["loop", "roll", "loop"]
    assert _acd_fig("A.21").elements[1].kwargs["rolltypes"] == "snap"


def test_acd_half_square_loop_integrated_rolls_are_one_mirror_option():
    fig = _acd_fig("A.24")
    first, snap, second = fig.elements
    # the 1/4 rolls span their corners, the second corner is in knife-edge
    assert first.kwargs["rollangle"] == pytest.approx(np.pi / 2) and first.kwargs["rollposition"] == 0.5
    assert snap.kwargs["rolltypes"] == "snap" and snap.kwargs["padded"] is True
    assert second.kwargs["ke"] == pytest.approx(np.pi / 2)
    assert "rollangle" not in second.kwargs
    assert fig.elements[0].kwargs["rolls"] == "roll_option[0]"
    assert second.args == ["roll_option[1]"] and second.kwargs["rolls"] == "roll_option[2]"
    values, mirror = fig.ndmps["roll_option"]
    assert mirror == [-v for v in values]
    # the exit attitude decides whether the quarter rolls go the same way
    same = np.sign(values[0]) == np.sign(values[2])
    assert same == (FIXTURE_BY_NUMBER["A.24"]["exit_attitude"] == FIXTURE_BY_NUMBER["A.24"]["entry_attitude"])
    assert set(k for k in fig.ndmps if k.startswith("roll_option")) == {"roll_option"}


def test_acd_half_square_loop_from_top_has_no_roll_in_the_other_direction():
    for text in (
        "Half square loop, half roll down",
        "Half square loop from top, half roll up",
    ):
        with pytest.raises(F3AParseError, match="expected"):
            parse_f3a_description(text)


def test_acd_immelmann_turn_ends_with_a_roll_after_a_line():
    for number, turns in (("D.1", np.pi), ("D.3", 2 * np.pi)):
        fig = _acd_fig(number)
        assert [e.kind for e in fig.elements] == ["loop", "line", "roll"]
        assert fig.elements[0].args == [pytest.approx(np.pi)]
        assert fig.elements[1].kwargs["length"] == "roll_line_length"
        assert fig.elements[2].args == [turns]
        assert fig.elements[2].kwargs["padded"] is False
        assert "roll_line_length" in fig.ndmps


def test_acd_knife_edge_immelmann_has_a_roll_at_each_end_and_one_mirror_option():
    fig = _acd_fig("D.7")
    assert [e.kind for e in fig.elements] == ["roll", "line", "loop", "line", "roll"]
    assert fig.elements[2].kwargs["ke"] == pytest.approx(np.pi / 2)
    assert set(k for k in fig.ndmps if k.startswith("roll_option")) == {"roll_option"}
    first, loop, last = fig.ndmps["roll_option"][0]
    assert (abs(first), abs(loop), abs(last)) == pytest.approx((np.pi / 2, np.pi, 1.5 * np.pi))
    # down: the half loop starts at the top
    assert _acd_fig("D.7").info.start.height == p.Height.TOP
    assert _acd_fig("D.5").info.start.height == p.Height.BTM


def test_acd_split_s_starts_with_the_roll_and_goes_down():
    fig = _acd_fig("C.3")
    assert [e.kind for e in fig.elements] == ["roll", "line", "loop"]
    assert fig.elements[0].args == [2 * np.pi] and fig.elements[2].args == [-np.pi]
    assert fig.info.start.height == p.Height.TOP


@pytest.mark.parametrize(
    "text, words",
    [
        ("Half square loop", "unexpected|expected"),
        ("Half square loop with banana up", "banana"),
        ("Half square loop from middle, half roll up", "not supported"),
        (
            "Half square loop from upright, 1/4 roll integrated, snap-roll, half roll integrated, exit upright",
            "expected a 0.25 roll",
        ),
        (
            "Half square loop from upright, 1/4 roll integrated, half roll, 1/4 roll integrated, exit upright",
            "expected a snap",
        ),
        (
            "Half square loop from upright, 1/4 roll integrated, snap-roll, 1/4 roll integrated",
            "exit attitude is missing",
        ),
        (
            "Half square loop from upright, 1/4 roll integrated, snap-roll, 1/4 roll integrated, exit upright, exit inverted",
            "unexpected|expected",
        ),
        ("Immelmann turn from top", "no start height"),
        ("Immelmann turn, banana", "banana"),
        ("Immelmann turn from upright with 1/4 roll, knife-edge half loop up, 1/2 roll, exit upright", "expected a 0.75 roll"),
        ("Immelmann turn from upright with 1/4 roll, half loop up, 3/4 roll, exit upright", "knife-edge half loop"),
        ("Immelmann turn from upright with 1/4 roll, knife-edge half loop up, 3/4 roll", "exit attitude is missing"),
        ("Split S, full roll", "from top"),
        ("Split S, from top", "expected one roll"),
    ],
)
def test_acd_figures_are_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


# ---------------------------------------------------------------- group 23


def _g23_kinds(fig):
    return [e.kind for e in fig.elements]


@pytest.mark.parametrize(
    "text, angles",
    [
        ("Two rolls reversed", [2 * np.pi, -2 * np.pi]),
        ("1 1/2 rolls reversed", [3 * np.pi, -3 * np.pi]),
        ("Two 2/2 pt. rolls reversed", [np.pi, np.pi, -np.pi, -np.pi]),
        ("Two 2/4 pt. rolls reversed", [np.pi / 2] * 2 + [-np.pi / 2] * 2),
    ],
)
def test_g23_reversed_rolls_are_one_padded_roll_with_opposite_stops(text, angles):
    fig = parse_f3a_description(f"23.1 {text} (K4)")
    assert _g23_kinds(fig) == ["roll"]
    (roll,) = fig.elements
    assert roll.kwargs["padded"] is True
    assert roll.args[0] == pytest.approx(angles)
    assert fig.ndmps == {}


def test_g23_point_rolls_and_snaps_are_one_centred_roll():
    for text, kind in [
        ("Four point roll", "roll"),
        ("Eight point roll", "roll"),
        ("One horizontal snap roll", "snap"),
        ("Two snap rolls reversed", "snap"),
    ]:
        (roll,) = parse_f3a_description(f"23.1 {text} (K4)").elements
        assert roll.kwargs["padded"] is True and roll.kwargs["rolltypes"] == kind
    assert parse_f3a_description("Four point roll").elements[0].args[0] == "4x4"
    assert parse_f3a_description("Eight point roll").elements[0].args[0] == "8x8"


def test_g23_roll_and_opposite_snap_are_one_roll_element():
    (roll,) = parse_f3a_description("2/2pt roll, full snap roll opposite").elements
    assert roll.kwargs["rolltypes"] == "rrs"
    assert roll.args[0] == pytest.approx([np.pi, np.pi, -2 * np.pi])
    (roll,) = parse_f3a_description("2/4pt roll, 1 1/2 snap roll opposite").elements
    assert roll.args[0] == pytest.approx([np.pi / 2, np.pi / 2, -3 * np.pi])


def test_g23_knife_edge_flight_is_a_quarter_roll_a_line_and_the_quarter_roll_back():
    fig = parse_f3a_description("Knife edge flight")
    assert _g23_kinds(fig) == ["roll", "line", "roll"]
    assert [e.kwargs["padded"] for e in fig.elements if e.kind == "roll"] == [False, False]
    # no extra lines next to the quarter rolls, and the side is a mirror option
    assert "roll_line_length" not in fig.ndmps
    first, second = fig.ndmps["roll_option"][0]
    assert first == pytest.approx(-second) and abs(first) == pytest.approx(np.pi / 2)
    assert fig.ndmps["roll_option"][1] == pytest.approx([-first, -second])


def test_g23_reverse_knife_edge_flight_has_a_half_roll_on_the_line():
    fig = parse_f3a_description("Reverse knife edge flight")
    assert _g23_kinds(fig) == ["roll", "roll", "roll"]
    assert [e.kwargs["padded"] for e in fig.elements] == [False, True, False]
    assert fig.elements[1].args[0] == pytest.approx(-np.pi)
    assert "roll_line_length" not in fig.ndmps
    first, second = fig.ndmps["roll_option"][0]
    assert first == pytest.approx(second)  # both quarter rolls the same way


@pytest.mark.parametrize(
    "text, words",
    [
        ("Knife edge flight, half roll", "unexpected"),
        ("Knife edge flight from top", "no start height"),
        ("Two rolls reversed, banana", "unexpected"),
        ("2/2pt roll, full roll opposite", "snap"),
        ("2/2pt roll", "expected"),
        ("Four point roll from top", "no start height"),
    ],
)
def test_g23_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


@pytest.mark.parametrize("number", ["23.17", "23.19", "23.18", "23.20"])
def test_g23_knife_edge_flights_finish_in_their_entry_attitude(number, mb):
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(entry["description"], number, entry["k"])
    orientation = p.Orientation.UPRIGHT if entry["entry_attitude"] == "upright" else p.Orientation.INVERTED
    for option in (0, 1):
        mdef = mb.create_mdef(fig)
        mdef.mps.data["roll_option"].defaul = option
        itrans = g.Transformation(g.Euler(orientation, 0, p.Heading.RTOL), g.P0())
        tp = State.stack(mdef.create().create_template(itrans), "element")
        belly = tp.att.transform_point(g.PZ())
        assert (belly.z[-1] < 0) == (entry["exit_attitude"] == "upright")


# ---------------------------------------------------------------- group E


def _kinds_e(text):
    fig = parse_f3a_description(text)
    return fig, [e.kind for e in fig.elements]


@pytest.mark.parametrize(
    "text, first, second",
    [
        ("Figure 9 from bottom, full roll up", 0.25, -0.75),
        ("Figure 9 from middle (top first), full roll down", 0.75, -0.25),
        ("Figure 6 from top, full roll down", -0.25, 0.75),
        ("Figure 6 from middle (bottom first), full roll up", -0.75, 0.25),
    ],
)
def test_e_figure_9_and_6_are_a_quarter_and_a_three_quarter_loop_round_a_vertical_roll(
    text, first, second
):
    fig, kinds = _kinds_e(text)
    assert kinds == ["loop", "roll", "loop"]
    loops = [e for e in fig.elements if e.kind == "loop"]
    assert [round(float(l.args[0]) / (2 * 3.141592653589793), 2) for l in loops] == [
        first, second,
    ]
    assert fig.info.position == p.Position.END


def test_e_figure_9_roll_direction_must_match_the_vertical_line():
    with pytest.raises(F3AParseError, match="roll down but the vertical line goes up"):
        parse_f3a_description("Figure 9 from bottom, full roll down")


@pytest.mark.parametrize(
    "text",
    [
        "Figure 9 from top, full roll down",
        "Figure 6 from bottom, full roll up",
        "Figure 9 from middle (bottom first), full roll down",
        "Figure 9 from bottom, full roll up, sideways",
        "Figure 9 from bottom",
        "Figure 9 from bottom upright with snap roll up, inverted entry"
        if False else "Figure 9 from bottom inverted with snap roll up, inverted entry",
    ],
)
def test_e_figures_are_strict(text):
    with pytest.raises(F3AParseError):
        parse_f3a_description(text)


def test_e_stated_exit_attitude_must_be_the_flown_one():
    # a half roll in the integrated loop would flip the exit
    with pytest.raises(F3AParseError, match="exits"):
        parse_f3a_description(
            "Figure 9 from bottom upright with integrated 1/2 roll in top 180 degree of loop, exit inverted"
        )


def test_e_integrated_roll_spans_the_first_half_of_the_three_quarter_loop():
    fig, kinds = _kinds_e(
        "Figure 6 from top upright with integrated 1/2 roll on bottom 180 degree of loop, exit upright"
    )
    assert kinds == ["loop", "line", "loop", "loop"]
    rolling, rest = fig.elements[2], fig.elements[3]
    assert abs(abs(float(rolling.args[0])) - 3.141592653589793) < 1e-9
    assert rolling.kwargs.get("rolls") is not None
    assert "rolls" not in rest.kwargs or not rest.kwargs["rolls"]
    with pytest.raises(F3AParseError, match="top 180 degrees"):
        parse_f3a_description(
            "Figure 6 from top upright with integrated 1/2 roll in top 180 degree of loop, exit upright"
        )


@pytest.mark.parametrize(
    "text, kinds",
    [
        (
            "Figure 9 from bottom upright with 1/4 roll up, 3/4 knife edge loop, 1/4 roll, exit inverted",
            ["loop", "roll", "loop", "line", "roll"],
        ),
        (
            "Figure 9 from middle inverted with 3 consecutive 1/4 rolls , 3/4 knife edge loop, 3 consecutive 1/4 rolls, exit upright",
            ["roll", "line", "loop", "roll", "loop"],
        ),
        (
            "Figure 6 from top inverted with 3/4 snap roll down, 3/4 knife edge loop, 3 consecutive 1/4 rolls, exit upright",
            ["loop", "roll", "loop", "line", "roll"],
        ),
    ],
)
def test_e_knife_edge_figures_have_one_mirror_option_for_rolls_and_loop(text, kinds):
    fig, found = _kinds_e(text)
    assert found == kinds
    assert set(fig.ndmps) == {"roll_option", "roll_line_length"}
    plus, minus = fig.ndmps["roll_option"]
    assert minus == [-v for v in plus]
    # the knife-edge loop, and every quarter roll piece of the two rolls
    assert any(abs(abs(v) - 1.5 * 3.141592653589793) < 1e-9 for v in plus)


def test_e_knife_edge_exit_attitude_selects_the_relative_roll_directions():
    same = parse_f3a_description(
        "Figure 9 from bottom upright with 1/4 roll up, 3/4 knife edge loop, 1/4 roll, exit upright"
    )
    other = parse_f3a_description(
        "Figure 9 from bottom upright with 1/4 roll up, 3/4 knife edge loop, 1/4 roll, exit inverted"
    )
    assert same.ndmps["roll_option"] != other.ndmps["roll_option"]


def test_e_knife_edge_rolls_must_leave_the_wings_vertical():
    with pytest.raises(F3AParseError, match="vertical"):
        parse_f3a_description(
            "Figure 9 from bottom upright with half roll up, 3/4 knife edge loop, 1/4 roll, exit upright"
        )


# ---------------------------------------------------------------- groups 24 and 25

DOUBLE_KEY = (
    "Double key: {entry}pull into vertical upline, 3/4 pt. roll up, 5/8 knife-edge loop towards "
    "the back, 3/4 roll down, {turn} into 45 degree upline, 3/4 roll up, 5/8 knife-edge loop "
    "towards the back, 3/4 pt.roll down, {exit} (K6)"
)


def _double_key(number: str) -> str:
    return FIXTURE_BY_NUMBER[number]["description"]


def test_g24_pt_dot_roll_without_a_space_is_normalised():
    assert normalise("3/4 pt.roll down") == "3/4-point roll down"
    assert normalise("3/4 pt. roll up") == "3/4-point roll up"


def test_g24_double_key_is_a_heart_of_two_knife_edge_loops():
    fig = parse_f3a_description(_double_key("24.1"), "24.1")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "roll", "loop", "roll", "loop", "roll", "loop"]
    loops = [e for e in fig.elements if e.kind == "loop"]
    # 1/4 up, 5/8 towards the back (a knife-edge yaw loop), 1/4 onto the 45 degree upline,
    # 5/8 towards the back, 1/4 out: all turning the same way
    assert [abs(e.args[0]) / (2 * np.pi) for e in loops if "ke" not in e.kwargs] == [0.25, 0.25, 0.25]
    ke = [e for e in fig.elements if "ke" in e.kwargs]
    assert len(ke) == 2
    first, _ = fig.ndmps["roll_option"]
    assert first[3] == pytest.approx(2 * np.pi * 5 / 8 * np.sign(first[0]))
    # 3/4 pt roll on the vertical upline (3 quarters), 3/4 rolls on the 45 degree lines
    rolls = [e for e in fig.elements if e.kind == "roll"]
    assert [len(e.args[0]) for e in rolls] == [3, 1, 1, 3]
    assert all(e.kwargs["padded"] for e in rolls)


@pytest.mark.parametrize("number, attitude", [("24.1", "upright"), ("24.2", "inverted"), ("24.3", "upright"), ("24.4", "inverted")])
def test_g24_pulled_or_pushed_loops_follow_the_attitudes(number, attitude):
    fig = parse_f3a_description(_double_key(number), number)
    quarter = [e.args[0] for e in fig.elements if e.kind == "loop" and "ke" not in e.kwargs]
    # element angles are positive for a pull and negative for a push: the loops all turn
    # the same way in the plane, so from inverted the quarter loops are pushes, but the
    # one onto the 45 degree upline is a pull or a push as the words say
    outer = 1 if attitude == "upright" else -1
    middle = 1 if number in ("24.1", "24.2") else -1
    assert np.sign(quarter).tolist() == [outer, middle, outer]
    assert fig.info.start.orientation == fig.info.end.orientation
    assert fig.info.start.orientation.name.lower() == attitude


def test_g24_the_two_halves_are_independent_mirror_options():
    # brute force over the free 3/4 roll signs: valid combinations are a product of
    # one pair per half, so the pilot can choose each half's side separately
    import itertools

    from pyolan.f3a.errors import F3AParseError as Err
    from pyolan.f3a.parser import description_clauses
    from pyolan.f3a.steps import Roll, _fly

    for number in ("24.1", "24.3"):
        clauses = description_clauses(split_description(_double_key(number), number))
        free = [i for i, c in enumerate(clauses) if isinstance(c, Roll)]
        valid = []
        for combination in itertools.product([1, -1], repeat=len(free)):
            try:
                _fly(clauses, dict(zip(free, combination)), True)
            except Err:
                continue
            valid.append(combination)
        assert len(valid) == 4
        # two choices for each half, all four pairings valid
        assert len({c[:2] for c in valid}) == 2 and len({c[2:] for c in valid}) == 2
    fig = parse_f3a_description(_double_key("24.1"), "24.1")
    assert {k for k in fig.ndmps if k.startswith("roll_option")} == {"roll_option", "roll_option_2"}
    for name in ("roll_option", "roll_option_2"):
        first, mirror = fig.ndmps[name]
        assert len(first) == 5 and mirror == [-v for v in first]


@pytest.mark.parametrize("choice", [(0, 0), (1, 0), (0, 1), (1, 1)])
@pytest.mark.parametrize("number", ["24.1", "24.2", "24.3", "24.4"])
def test_g24_either_side_of_each_half_closes_at_the_entry_height(number, choice, mb):
    mdef = mb.create_mdef(parse_f3a_description(_double_key(number), number))
    for name, value in zip(("roll_option", "roll_option_2"), choice):
        mdef.mps.data[name].defaul = value
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    z = State.stack(templates, "element").pos.z
    assert float(z[-1] - z[0]) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize(
    "old, new, words",
    [
        ("5/8 knife-edge loop towards the back,", "5/8 knife-edge loop towards the front,", "towards the front"),
        ("3/4 roll down, pull", "3/4 roll up, pull", "roll down"),
        ("3/4 roll up, 5/8", "1/2 roll up, 5/8", "3/4 roll"),
        ("pull into 45 degree upline", "pull into 60 degree upline", "60 degree"),
        ("pull to exit upright", "pull to exit inverted", "pull to exit inverted"),
        ("pull into vertical upline", "push into vertical upline", "push into the upline"),
    ],
)
def test_g24_double_key_is_strict(old, new, words):
    text = _double_key("24.1").replace(old, new)
    assert text != _double_key("24.1")
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


def test_g24_double_key_needs_all_its_steps():
    with pytest.raises(F3AParseError, match="nine steps"):
        parse_f3a_description("Double key: pull into vertical upline, 3/4 pt. roll up")


@pytest.mark.parametrize("number, rolls", [("25.1", 1), ("25.3", 2), ("25.5", 4)])
@pytest.mark.parametrize("inverted", [False, True])
def test_g25_horizontal_eight_is_a_three_quarter_loop_a_full_loop_and_a_quarter(number, rolls, inverted):
    number = number if not inverted else f"25.{int(number[-1]) + 1}"
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number)
    loops = fig.elements
    assert [e.kind for e in loops] == ["loop", "loop", "loop"]
    sign = -1 if inverted else 1
    assert [round(e.args[0] / (2 * np.pi), 3) for e in loops] == [0.75 * sign, -1.0 * sign, 0.25 * sign]
    # the roll (whole rolls) is integrated through the loop piece, in the first two loops only
    for loop, piece in zip(loops[:2], (0.75, 1.0)):
        assert loop.kwargs["rollangle"] == pytest.approx(piece * 2 * np.pi)
        assert loop.kwargs["rollposition"] == pytest.approx(0.5)
        assert abs(loop.kwargs["rolls"]) == pytest.approx(2 * np.pi * rolls)
    assert "rolls" not in loops[2].kwargs
    assert fig.info.start.orientation == fig.info.end.orientation
    assert (fig.info.start.orientation == p.Orientation.INVERTED) == inverted


@pytest.mark.parametrize("number", [f"25.{n}" for n in range(1, 7)])
def test_g25_horizontal_eight_finishes_at_its_entry_height(number, mb):
    mdef = mb.create_mdef(parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number))
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    pos = State.stack(templates, "element").pos
    assert float(pos.z[-1] - pos.z[0]) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize(
    "text, words",
    [
        ("Horizontal eight", "integrated in each loop"),
        ("Horizontal eight with one snap integrated in each loop", "whole rolls"),
        ("Horizontal eight with half roll integrated in each loop", "whole rolls"),
        ("Horizontal eight from top with one roll integrated in each loop", "start height"),
        ("Horizontal eight with one roll integrated in each loop, banana", "banana|expected"),
    ],
)
def test_g25_horizontal_eight_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


# ---------------------------------------------------------------- groups G (spins) and H (stall turns)


def _gh_fig(number):
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(entry["description"], number, entry["k"])
    assert isinstance(fig, a.Figure)
    return fig


def _gh_states(fig, mb, option=0):
    mdef = mb.create_mdef(fig)
    for name, mp in mdef.mps.data.items():
        if name.startswith("roll_option") or name.endswith("_turns"):
            mp.defaul = option
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(fig.info.start.orientation, 0, p.Heading.RTOL), g.P0())
    )
    return State.stack(templates, "element")


@pytest.mark.parametrize(
    "g_number, number_19",
    [("G.3", "19.1"), ("G.5", "19.9"), ("G.6", "19.10"), ("G.7", "19.11"), ("G.8", "19.12")],
)
def test_gh_spins_have_the_elements_of_the_group_19_spins_and_leave_the_other_way(g_number, number_19):
    fig, centre = _gh_fig(g_number), _fig19(number_19)
    assert [e.kind for e in fig.elements] == [e.kind for e in centre.elements]
    assert fig.info.position == p.Position.END and centre.info.position == p.Position.CENTRE
    # the 1/4 loop out is flown the other way round (the knife-edge loops' direction
    # is in the mirror option, which is the same spin and loop but reversed in sense)
    loop, centre_loop = fig.elements[-1], centre.elements[-1]
    assert loop.kind == "loop"
    if g_number == "G.3":
        assert loop.args == [-v for v in centre_loop.args]
    else:
        assert fig.ndmps["roll_option"][0][1] == -centre.ndmps["roll_option"][0][1]


def test_gh_two_turn_spin_is_a_spin_a_downline_and_a_loop_out():
    fig = _gh_fig("G.1")
    assert [e.kind for e in fig.elements] == ["spin", "line", "loop"]
    assert fig.elements[0].args == [pytest.approx(4 * np.pi)]
    # whole turns: the loop out is pushed, so the exit is inverted and flown back
    assert (fig.info.start.orientation, fig.info.end.orientation) == (
        p.Orientation.UPRIGHT,
        p.Orientation.INVERTED,
    )
    assert not fig.ndmps


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize("number", [f"G.{n}" for n in range(1, 9)])
def test_gh_spin_figures_turn_round_and_exit_in_the_stated_attitude(number, option, mb):
    fig = _gh_fig(number)
    states = _gh_states(fig, mb, option)
    belly = states.att.transform_point(g.PZ()).z[-1]
    assert (belly > 0) == (fig.info.end.orientation == p.Orientation.INVERTED)
    nose = states.att.transform_point(g.PX())
    assert nose.x[0] * nose.x[-1] < 0
    assert float(states.pos.z[-1] - states.pos.z[0]) < 0


@pytest.mark.parametrize(
    "text, words",
    [
        ("Two turn spin, half roll exit", "unexpected"),
        ("Two turn spin, banana", "banana"),
        ("Two turn spin, inverted entry. Entry upright", "entry attitude"),
    ],
)
def test_gh_two_turn_spin_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description("G.1 " + text)


@pytest.mark.parametrize("number", [f"H.{n}" for n in range(3, 17)])
def test_gh_stall_turn_has_a_centred_roll_on_each_line_and_turns_round(number, mb):
    fig = _gh_fig(number)
    assert [e.kind for e in fig.elements] == ["loop", "roll", "stallturn", "roll", "loop"]
    assert all(e.kwargs["padded"] for e in fig.elements if e.kind == "roll")
    assert fig.info.position == p.Position.END
    # the group 20 convention: the entry is at the middle of the vertical and the
    # figure ends as far below it as it rises above it (a snap's pads are sized
    # for 15 m but it flies 17.6 m, so the exit is up to 2.6 m low)
    states = _gh_states(fig, mb)
    z = np.asarray(states.pos.z)
    assert float(z.max() - z[0] - (z[0] - z[-1])) == pytest.approx(0, abs=3.5)
    assert float(states.pos.y[-1] - states.pos.y[0]) == pytest.approx(0, abs=1e-6)
    nose = states.att.transform_point(g.PX())
    assert nose.x[0] * nose.x[-1] < 0


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize("number", [f"H.{n}" for n in range(3, 17)])
def test_gh_stall_turn_exits_in_the_drawn_attitude_in_both_directions(number, option, mb):
    fig = _gh_fig(number)
    states = _gh_states(fig, mb, option)
    belly = states.att.transform_point(g.PZ()).z[-1]
    assert (belly > 0) == (FIXTURE_BY_NUMBER[number]["exit_attitude"] == "inverted")


@pytest.mark.parametrize(
    "text, entry, exit_",
    [
        # an even number of half rolls in all keeps the attitude, an odd one flips it
        ("Stall turn, half roll up, half roll down", "upright", "upright"),
        ("Stall turn, half roll up, half roll down, inverted entry", "inverted", "inverted"),
        ("Stall turn, full roll up, half roll down", "upright", "inverted"),
        ("Stall turn, full roll up, half roll down, inverted entry", "inverted", "upright"),
        ("Stall turn, full roll up, full roll down, inverted entry", "inverted", "inverted"),
        # quarter rolls: the directions are the pilot's, the drawings leave upright
        ("Stall turn, 3/4 roll up, 1/4 roll down, inverted entry", "inverted", "upright"),
    ],
)
def test_gh_stall_turn_exit_attitude_follows_the_rolls(text, entry, exit_):
    fig = parse_f3a_description("H.1 " + text)
    assert fig.info.start.orientation.name.lower() == entry
    assert fig.info.end.orientation.name.lower() == exit_


def test_gh_stall_turn_with_quarter_rolls_links_them_in_one_mirror_option():
    fig = _gh_fig("H.14")
    assert set(k for k in fig.ndmps if k.startswith("roll_option")) == {"roll_option"}
    first, mirror = fig.ndmps["roll_option"]
    assert mirror == [-v for v in first]


def test_gh_stall_turn_rolls_without_a_comma_are_read():
    fig = parse_f3a_description("H.14 Stall turn, 3/4pt roll up 1/4 roll down, inverted entry (K3)")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "stallturn", "roll", "loop"]


def test_gh_group_20_stall_turn_is_unchanged_by_the_turnaround_exit_rule():
    # a numbered group is a centre figure that leaves upright whatever the entry
    fig = parse_f3a_description("20.2 Stall turn, 3/4 roll up, 3/4pt roll down, inverted entry (K3)")
    assert fig.info.position == p.Position.CENTRE
    assert fig.info.end.orientation == p.Orientation.UPRIGHT


# ---------------------------------------------------------------- group F


def _f_loops(number):
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number)
    return fig, [round(e.args[0] / (2 * np.pi), 4) for e in fig.elements if e.kind == "loop"]


@pytest.mark.parametrize(
    "number, loops",
    [
        ("F.3", [0.625, 0.125]),  # 5/8 loop up and over, 45 degree line down, 1/8 loop out
        ("F.4", [-0.625, -0.125]),  # inverted entry: the same figure with pushed loops...
        ("F.15", [-0.625, -0.125]),  # from top: the mirror image, loop down
        ("F.16", [0.625, 0.125]),
        ("F.23", [0.125, 0.625]),  # reverse: the 1/8 loop first
        ("F.35", [-0.125, -0.625]),
    ],
)
def test_f_half_cuban_eights_have_a_5_8_and_a_1_8_loop_and_a_roll_on_the_45_degree_line(number, loops):
    fig, found = _f_loops(number)
    # the pull or push of the loops depends on the roll, so only the amounts are compared
    assert [abs(x) for x in found] == pytest.approx([abs(x) for x in loops])
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop"]
    roll = fig.elements[1]
    assert roll.kwargs["padded"] is True
    assert roll.kwargs["line_length"] == "loop_radius"


@pytest.mark.parametrize("number", ["F.3", "F.9", "F.23", "F.41", "F.49", "F.53"])
def test_f_half_cuban_eights_are_turnarounds(number):
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number)
    assert fig.info.position == p.Position.END


def test_f_plain_half_reverse_cuban_eight_has_no_roll_and_turns_the_figure_over():
    fig = parse_f3a_description("F.22 Half reverse cuban eight, inverted entry (K2)")
    assert [e.kind for e in fig.elements] == ["loop", "line", "loop"]
    assert fig.info.start.orientation == p.Orientation.INVERTED
    assert fig.info.end.orientation == p.Orientation.UPRIGHT


@pytest.mark.parametrize(
    "number, same",
    [("F.3", True), ("F.5", False), ("F.7", False), ("F.9", False), ("F.11", True)],
)
def test_f_exit_attitude_follows_from_the_roll(number, same):
    # the figure itself is a half turn about the wings, so a half roll or 1 1/2 snap
    # brings the pilot back to the entry attitude and a full roll or snap does not
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number)
    assert (fig.info.end.orientation == fig.info.start.orientation) == same


@pytest.mark.parametrize("number", [f"F.{n}" for n in range(41, 49)])
def test_f_integrated_roll_spreads_over_the_first_half_loop(number):
    fig, loops = _f_loops(number)
    assert [e.kind for e in fig.elements] == ["loop", "loop", "line", "loop"]
    first = fig.elements[0]
    # up from the bottom (down from top); an inverted entry pushes
    up = "up with" in FIXTURE_BY_NUMBER[number]["description"]
    inverted = "from inverted" in FIXTURE_BY_NUMBER[number]["description"]
    assert first.args[0] == pytest.approx(np.pi if up != inverted else -np.pi)
    # spread over the whole half loop, centred on it
    assert first.kwargs["rollangle"] == pytest.approx(np.pi)
    assert first.kwargs["rollposition"] == 0.5
    whole = "1/2 roll" not in FIXTURE_BY_NUMBER[number]["description"]
    assert abs(first.kwargs["rolls"]) == pytest.approx(2 * np.pi if whole else np.pi)
    assert "rolls" not in fig.elements[1].kwargs
    assert fig.elements[2].kwargs["length"] == "loop_radius"


def _f_template_path(number, mb, radius=150.0):
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number)
    mdef = mb.create_mdef(fig)
    mdef.mps.data["loop_radius"].defaul = radius
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = 0
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(fig.info.start.orientation, 0, p.Heading.RTOL), g.P0())
    )
    return fig, State.stack(templates, "element")


@pytest.mark.parametrize(
    "down, up",
    [("F.45", "F.42"), ("F.46", "F.41"), ("F.47", "F.44"), ("F.48", "F.43")],
)
def test_f_half_cuban_down_is_the_top_to_bottom_mirror_of_a_half_cuban(down, up, mb):
    # decided 2026-11-20 (A4 review): the figure from the entry goes down round a 5/8 loop, a
    # 45 degree line up and a 1/8 loop to level, the mirror (top to bottom) of the half Cuban
    # eight up, so an upright pilot entering down is the mirror of an inverted one entering up.
    # The roll is over the first 180 degrees only, finishing at the half-loop point.
    fig_down, path_down = _f_template_path(down, mb)
    fig_up, path_up = _f_template_path(up, mb)
    assert [e.kind for e in fig_down.elements] == ["loop", "loop", "line", "loop"]
    # 5/8 loop down: the 45 degree line then goes UP (loop 1/8 more, 1/8 back to level)
    assert [round(abs(e.args[0]) / (2 * np.pi), 4) for e in fig_down.elements if e.kind == "loop"] == [0.5, 0.125, 0.125]
    assert fig_down.elements[0].kwargs["rollposition"] == 0.5 and "rolls" not in fig_down.elements[1].kwargs
    # the mirror: the same positions in plan, the heights reversed
    np.testing.assert_allclose(path_down.pos.x, path_up.pos.x, atol=1e-6)
    np.testing.assert_allclose(path_down.pos.z, -path_up.pos.z, atol=1e-6)
    # the attitudes are the words'
    assert fig_down.info.start.orientation == (
        p.Orientation.INVERTED if "from inverted" in FIXTURE_BY_NUMBER[down]["description"] else p.Orientation.UPRIGHT
    )
    assert fig_down.info.end.orientation == (
        p.Orientation.INVERTED if "exit inverted" in FIXTURE_BY_NUMBER[down]["description"] else p.Orientation.UPRIGHT
    )


@pytest.mark.parametrize("number", [f"F.{n}" for n in (49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64)])
def test_f_knife_edge_versions_link_the_rolls_and_the_loop_in_one_mirror_option(number):
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number)
    option = fig.ndmps["roll_option"]
    assert option[1] == [-v for v in option[0]]
    # three quarter rolls, the knife-edge loop and the 3/4 roll
    assert [abs(v) for v in option[0][:3]] == pytest.approx([np.pi / 2] * 3)
    assert abs(option[0][3]) == pytest.approx(5 * np.pi / 4)
    assert abs(option[0][4]) == pytest.approx(3 * np.pi / 2)
    assert sum(1 for e in fig.elements if e.kind == "loop" and e.kwargs.get("ke")) == 1
    assert "roll_line_length" in fig.ndmps
    rolls = [e for e in fig.elements if e.kind == "roll"]
    assert [len(r.args[0]) for r in rolls] == [3, 1]


@pytest.mark.parametrize("exit_attitude, same", [("upright", True), ("inverted", False)])
def test_f_knife_edge_exit_attitude_decides_whether_the_two_rolls_go_the_same_way(exit_attitude, same):
    # the figure is a half turn about the wings: two 3/4 rolls the same way bring the
    # pilot back upright, opposite ones leave the pilot inverted
    fig = parse_f3a_description(
        "Half cuban eight from upright with 3 consecutive 1/4 rolls, 5/8 knife edge loop, "
        f"3/4 roll, exit {exit_attitude}"
    )
    values = fig.ndmps["roll_option"][0]
    assert (values[0] * values[4] > 0) == same


@pytest.mark.parametrize(
    "text, words",
    [
        ("Half cuban eight, 2/4pt roll up", "goes down"),
        ("Half cuban eight from top, 2/4pt roll down", "goes up"),
        ("Half reverse cuban eight from top, full roll up", "goes down"),
        ("Half cuban eight from middle, full roll", "not supported"),
        ("Half cuban eight, full roll, 2/4pt roll", "expected one roll"),
        ("Half cuban eight, banana", "not a roll"),
        ("Half reverse cuban eight from upright up with 1/2 roll integrated in first 180 degree of loop, exit upright", "forward"),
        ("Half Cuban Eight from upright up with 1/2 roll integrated in first 180 degree of loop", "exit attitude is missing"),
        ("Half cuban eight from upright with 3 consecutive 1/4 rolls, 5/8 knife edge loop, 1/2 roll, exit upright", "expected a 0.75 roll"),
        ("Half cuban eight from upright with 3 consecutive 1/4 rolls, 3/4 knife edge loop, 3/4 roll, exit upright", "5/8 knife-edge loop"),
        ("Half cuban eight from upright with 3 consecutive 1/4 rolls, 5/8 knife edge loop, 3/4 roll, exit inverted, exit upright", "unexpected|twice|given"),
    ],
)
def test_f_half_cuban_eights_are_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


# ---------------------------------------------------------------- group N (half square loop on corner)


def _n_fig(number):
    return _acd_fig(number)


@pytest.mark.parametrize("number", [f"N.{n}" for n in range(1, 29)])
def test_n_half_square_loop_on_corner_is_two_45_degree_legs_with_a_centred_roll_each(number):
    fig = _n_fig(number)
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "roll", "loop"]
    # the knife-edge corner (a yaw loop) holds its angle in the mirror option, its size in "ke"
    loops = [
        abs(e.kwargs["ke"] if isinstance(e.args[0], str) else e.args[0]) / (2 * np.pi)
        for e in fig.elements
        if e.kind == "loop"
    ]
    assert loops == pytest.approx([1 / 8, 1 / 4, 1 / 8])
    assert fig.info.position == p.Position.END
    # one line length for both legs
    # both rolls sit on padded lines of the default line length (no length of its own)
    for roll in (fig.elements[1], fig.elements[3]):
        assert roll.kwargs["padded"] is True
        assert "line_length" not in roll.kwargs


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize("number", [f"N.{n}" for n in range(1, 29)])
def test_n_figures_leave_in_the_stated_attitude_in_both_mirror_options(number, option, mb):
    entry = FIXTURE_BY_NUMBER[number]
    states = _acd_states(_n_fig(number), mb, option)
    belly = states.att.transform_point(g.PZ()).z
    assert ("inverted" if belly[0] > 0 else "upright") == entry["entry_attitude"]
    assert ("inverted" if belly[-1] > 0 else "upright") == entry["exit_attitude"]
    nose = states.att.transform_point(g.PX()).x
    assert nose[0] * nose[-1] < 0
    assert (float(states.pos.z[-1] - states.pos.z[0]) > 0) == (entry["exit_height"] == "high")


@pytest.mark.parametrize("number", ["N.1", "N.2", "N.13", "N.20", "N.28"])
def test_n_quarter_type_rolls_are_one_mirror_option(number):
    fig = _n_fig(number)
    option = fig.ndmps["roll_option"]
    assert option[1] == [-v for v in option[0]]
    assert "roll_option_2" not in fig.ndmps


@pytest.mark.parametrize("number", ["N.9", "N.10", "N.11", "N.12"])
def test_n_snaps_leave_their_direction_to_the_pilot(number):
    assert "roll_option" not in _n_fig(number).ndmps


@pytest.mark.parametrize(
    "number, first, second",
    [("N.1", 0.25, 0.25), ("N.9", 1.0, 1.0), ("N.13", 1.25, 0.75), ("N.21", 1.25, 1.25), ("N.28", 1.25, 1.25)],
)
def test_n_rolls_have_the_stated_amounts(number, first, second):
    fig = _n_fig(number)
    if "roll_option" in fig.ndmps:  # quarter-type rolls: values of the mirror option, rolls first and last
        values = fig.ndmps["roll_option"][0]
        amounts = [abs(values[0]), abs(values[2])]
    else:
        amounts = [e.args[0] for e in fig.elements if e.kind == "roll"]
    assert [abs(x) / (2 * np.pi) for x in amounts] == pytest.approx([first, second])


@pytest.mark.parametrize(
    "text, words",
    [
        ("Half Square Loop on Corner from upright up with 1/4 roll on first leg, exit upright", "expected"),
        ("Half Square Loop on Corner from upright up with 1/4 roll on first leg, 1/4 roll on first leg, exit upright", "expected a roll on each leg"),
        ("Half Square Loop on Corner from upright with 1/4 roll on first leg, 1/4 roll on second leg, exit upright", "expected"),
        ("Half Square Loop on Corner from upright up with 1/4 roll on first leg, 1/4 roll on second leg", "exit attitude is missing"),
        ("Half Square Loop on Corner from top from upright up with 1/4 roll on first leg, 1/4 roll on second leg, exit upright", "not supported"),
        ("Half Square Loop on Corner from upright up with 1/4 roll on first leg, banana on second leg, exit upright", "banana"),
        ("Half Square Loop on Corner from upright up with 1/2 roll on first leg, 1/2 roll on second leg, exit upright", "exits"),
    ],
)
def test_n_half_square_loop_on_corner_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


# ---------------------------------------------------------------- groups 27 to 30


def _g2730_template(number: str, mb, option: int = 0, **params):
    """The figure of a catalogue entry and its element-stacked template, entered as drawn."""
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(entry["description"], number, entry["k"])
    mdef = mb.create_mdef(fig)
    for key, value in params.items():
        mdef.mps.data[key].defaul = value
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = option
    attitude = p.Orientation.UPRIGHT if entry["entry_attitude"] == "upright" else p.Orientation.INVERTED
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(attitude, 0, p.Heading.RTOL), g.P0())
    )
    return fig, templates, State.stack(templates, "element")


def _g2730_exit_attitude(states) -> str:
    return "inverted" if float(states.att.transform_point(g.PZ()).z[-1]) > 0 else "upright"


def _g2730_kinds(number: str) -> list[str]:
    entry = FIXTURE_BY_NUMBER[number]
    return [e.kind for e in parse_f3a_description(entry["description"], number, entry["k"]).elements]


def test_g27_infinite_loop_is_two_half_loops_joined_by_a_45_degree_line_with_the_snaps():
    for number, sign in (("27.1", 1), ("27.2", -1)):
        fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number, 6)
        assert [e.kind for e in fig.elements] == ["loop", "loop", "roll", "loop", "loop"]
        half1, eighth1, snaps, eighth2, half2 = fig.elements
        # pulled or pushed as the words say: from upright the first 1/8 is pushed, the second
        # pulled (the other way round from inverted); the half rolls flip each half loop's end
        assert [np.sign(e.args[0]) for e in (half1, eighth1, eighth2, half2)] == [sign, -sign, sign, sign]
        assert abs(half1.args[0]) == pytest.approx(np.pi) and abs(eighth1.args[0]) == pytest.approx(np.pi / 4)
        # the half rolls are spread over their half loops
        for loop in (half1, half2):
            assert loop.kwargs["rolls"] == pytest.approx(np.pi)
            assert loop.kwargs["rollangle"] == pytest.approx(np.pi)
            assert loop.kwargs["rollposition"] == 0.5
        # two opposite snaps: one roll element, the second reversed, on a padded diagonal that
        # makes the second half loop end at the entry height
        assert snaps.kwargs["rolltypes"] == "snap" and snaps.kwargs["padded"]
        assert snaps.args[0] == pytest.approx([2 * np.pi, -2 * np.pi])
        assert snaps.kwargs["line_length"] == "(4.8284*loop_radius)"
        assert fig.ndmps == {}
        assert fig.info.position == p.Position.CENTRE


@pytest.mark.parametrize("number", ["27.3", "27.4"])
def test_g27_infinite_loop_with_rolls_has_four_quarter_rolls_in_and_two_opposite_half_rolls_out(number):
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number, 6)
    assert [e.kind for e in fig.elements] == [
        "roll", "line", "loop", "loop", "roll", "loop", "loop", "line", "roll",
    ]
    first, start_line, *_, end_line, last = fig.elements
    assert first.args[0] == "4x4" and not first.kwargs["padded"]
    assert start_line.kwargs["length"] == end_line.kwargs["length"] == "roll_line_length"
    assert last.args[0] == pytest.approx([np.pi, -np.pi])
    assert fig.ndmps["roll_line_length"].like == "line_length"


@pytest.mark.parametrize("number", ["27.1", "27.2", "27.3", "27.4"])
@pytest.mark.parametrize("radius", [55.0, 80.0])
def test_g27_infinite_loop_finishes_in_the_middle_on_the_entry_line_whatever_the_radius(number, radius, mb):
    entry = FIXTURE_BY_NUMBER[number]
    fig, _, states = _g2730_template(number, mb, loop_radius=radius)
    z = np.asarray(states.pos.z)
    # the two snaps' pads are sized for 15 m each but they fly 17.6 m: the line is 5 m long,
    # 3.6 m of it down the diagonal (builder inconsistency, not tied by the parser)
    assert float(z[-1] - z[0]) == pytest.approx(-3.6148, abs=0.01)
    assert float(states.pos.y[-1] - states.pos.y[0]) == pytest.approx(0, abs=1e-6)
    # the figure goes down the diagonal and comes back up to the entry height: the lowest point
    # is a half loop below, the highest a half loop above
    assert float(z.min() + z.max() - 2 * z[0]) == pytest.approx(0, abs=4)
    nose = states.att.transform_point(g.PX())
    assert nose.x[0] * nose.x[-1] > 0
    assert _g2730_exit_attitude(states) == entry["exit_attitude"]


def test_g27_infinite_loop_is_strict():
    base = FIXTURE_BY_NUMBER["27.1"]["description"]
    for text, words in (
        (base.replace(", 1/8 pushed loop", ""), "1/8"),
        (base.replace("two opposite snap-rolls", "two snap-rolls"), "two opposite"),
        (base.replace("exit upright", "exit upright, half roll"), "half roll"),
        (base.replace("From upright", "From top"), "from upright"),
        (base.replace("1/2 loop with integrated 1/2 roll", "1/2 loop with integrated 1/3 roll"), "1/3|not a roll|1/2"),
    ):
        with pytest.raises(F3AParseError, match=words):
            parse_f3a_description(text)
    # a stated pulled or pushed loop that the roll makes the other way round is refused
    with pytest.raises(F3AParseError, match="not pulled|not pushed"):
        parse_f3a_description(base.replace("1/8 pushed loop", "1/8 pulled loop"))


@pytest.mark.parametrize("number", ["28.1", "28.2", "28.3", "28.4"])
def test_g28_figure_h_is_two_stall_turn_verticals_joined_by_a_knife_edge_line(number):
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number, 6)
    assert [e.kind for e in fig.elements] == [
        "loop", "roll", "stallturn", "line", "loop", "roll", "loop", "line", "stallturn", "roll", "loop",
    ]
    loops = [e for e in fig.elements if e.kind == "loop"]
    assert [bool(e.kwargs.get("ke")) for e in loops] == [False, True, True, False]
    rolls = [e for e in fig.elements if e.kind == "roll"]
    assert [e.kwargs["rolltypes"] for e in rolls] == ["snap", "roll", "snap"]
    assert all(e.kwargs["padded"] for e in rolls)
    # the lines either side of the knife-edge flight (drawn, not in the words) are equal and
    # short, so the figure ends at its entry height whatever they are
    short = [e for e in fig.elements if e.kind == "line"]
    assert [e.kwargs["length"] for e in short] == ["(0.25*line_length)"] * 2
    # no roll ends the figure: the words' "1/4 roll" is the loop out (see the module text)
    assert fig.elements[-1].kind == "loop"
    assert fig.info.position == p.Position.CENTRE


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize("number", ["28.1", "28.2", "28.3", "28.4"])
def test_g28_figure_h_exits_in_the_drawn_attitude_and_closes_in_both_directions(number, option, mb):
    entry = FIXTURE_BY_NUMBER[number]
    fig, _, states = _g2730_template(number, mb, option)
    assert _g2730_exit_attitude(states) == entry["exit_attitude"]
    assert float(states.pos.z[-1] - states.pos.z[0]) == pytest.approx(0, abs=1e-6)
    assert float(states.pos.y[-1] - states.pos.y[0]) == pytest.approx(0, abs=1e-6)
    # the two snaps and both knife-edge loops are one mirror option (the exit attitude
    # depends on the snaps' relative direction)
    first, mirror = fig.ndmps["roll_option"]
    assert len(first) == 4 and mirror == [-v for v in first]
    assert set(k for k in fig.ndmps if k.startswith("roll_option")) == {"roll_option"}


def test_g28_figure_h_exit_attitude_follows_from_the_snaps_directions():
    same = parse_f3a_description(FIXTURE_BY_NUMBER["28.2"]["description"], "28.2", 6).ndmps["roll_option"][0]
    opposite = parse_f3a_description(FIXTURE_BY_NUMBER["28.1"]["description"], "28.1", 6).ndmps["roll_option"][0]
    assert np.sign(same[0]) == np.sign(same[3]) and np.sign(opposite[0]) != np.sign(opposite[3])


def test_g28_figure_h_is_strict():
    base = FIXTURE_BY_NUMBER["28.1"]["description"]
    for text, words in (
        (base.replace("stall turn, 1/4 knife-edge loop, line", "1/4 knife-edge loop, line"), "stall turn"),
        (base.replace("line with roll", "1/2 roll"), "line with roll"),
        (base.replace("1/4 roll. Exit", "1/4 roll, 1/4 roll. Exit"), "exit"),
        (base.replace("3/4 snap-roll, stall", "1 1/4 snap-roll, stall"), "3/4 snap"),
        (base.replace("Exit upright", "Exit"), "exit"),
    ):
        with pytest.raises(F3AParseError, match=words):
            parse_f3a_description(text)


@pytest.mark.parametrize("number", [f"29.{n}" for n in range(1, 9)])
def test_g29_half_clover_leaf_is_two_knife_edge_lobes_on_one_vertical_line(number):
    fig = parse_f3a_description(FIXTURE_BY_NUMBER[number]["description"], number, 5)
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "roll", "loop", "roll", "loop"]
    entry_loop, up, lobe1, snap, lobe2, down, exit_loop = fig.elements
    assert [e.kwargs["rolltypes"] for e in (up, snap, down)] == ["roll", "snap", "roll"]
    # both lobes are 3/4 knife-edge loops, joined by a line of two loop radii that carries
    # the snap (the loops are then tangent to the vertical line)
    assert [e.kwargs.get("ke") for e in (entry_loop, lobe1, lobe2, exit_loop)] == [None, np.pi / 2, np.pi / 2, None]
    assert snap.kwargs["line_length"] == "(2*loop_radius)"
    assert all(e.kwargs["padded"] for e in (up, snap, down))
    # the 3/4 rolls and the lobes' yaw directions are one mirror option; the snap is not
    # linked (the exit attitude does not depend on it)
    values = fig.ndmps["roll_option"][0]
    assert [abs(v) for v in values] == pytest.approx([1.5 * np.pi] * 4)
    # from the top the loops go down, from the bottom up
    sense = np.sign(entry_loop.args[0])
    assert sense == (-1 if "top" in FIXTURE_BY_NUMBER[number]["description"].lower().split(",")[0] else 1) * (
        1 if FIXTURE_BY_NUMBER[number]["entry_attitude"] == "upright" else -1
    )


def test_g29_half_clover_leaf_from_top_is_the_mirror_image_in_height(mb):
    bottom = _g2730_template("29.1", mb)[2]
    top = _g2730_template("29.5", mb)[2]
    assert np.asarray(top.pos.z) == pytest.approx(-np.asarray(bottom.pos.z), abs=1e-6)
    assert np.asarray(top.pos.x) == pytest.approx(np.asarray(bottom.pos.x), abs=1e-6)


@pytest.mark.parametrize("option", [0, 1])
@pytest.mark.parametrize("number", [f"29.{n}" for n in range(1, 9)])
def test_g29_half_clover_leaf_exits_in_the_drawn_attitude_and_closes_in_both_directions(number, option, mb):
    entry = FIXTURE_BY_NUMBER[number]
    fig, templates, states = _g2730_template(number, mb, option)
    assert _g2730_exit_attitude(states) == entry["exit_attitude"]
    assert float(states.pos.z[-1] - states.pos.z[0]) == pytest.approx(0, abs=1e-6)
    assert float(states.pos.y[-1] - states.pos.y[0]) == pytest.approx(0, abs=1e-6)
    first, mirror = fig.ndmps["roll_option"]
    assert len(first) == 4 and mirror == [-v for v in first]
    # the second lobe comes back down the line the first went up (to the snap's 2.6 m)
    assert float(templates["e_4"].pos.x[-1] - templates["e_0"].pos.x[-1]) == pytest.approx(0, abs=3)
    # a centre figure: it leaves the way it came in
    nose = states.att.transform_point(g.PX())
    assert nose.x[0] * nose.x[-1] > 0


def test_g29_half_clover_leaf_is_strict():
    base = FIXTURE_BY_NUMBER["29.1"]["description"]
    for text, words in (
        (base.replace("From bottom upright", "From middle upright"), "from"),
        (base.replace("snap-roll, 3/4", "1/2 roll, 3/4"), "snap"),
        (base.replace("3/4 knife-edge loop, snap", "1/2 knife-edge loop, snap"), "3/4 knife-edge"),
        (base.replace("Exit upright.", "Exit upright. 1/4 roll"), "unexpected|exit"),
    ):
        with pytest.raises(F3AParseError, match=words):
            parse_f3a_description(text)


@pytest.mark.parametrize("number", ["30.1", "30.2", "30.3", "30.4"])
def test_g30_diamond_in_a_loop_is_a_loop_with_opposite_half_rolls_then_a_square_loop_on_corner(number):
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(entry["description"], number, 5)
    assert [e.kind for e in fig.elements] == [
        "loop", "loop", "roll", "loop", "roll", "loop", "roll", "loop", "roll", "loop",
    ]
    circle, *rest = fig.elements
    # one loop, with a half roll spread over each of its halves, the second reversed
    assert abs(circle.args[0]) == pytest.approx(2 * np.pi)
    assert circle.kwargs["rolls"] == pytest.approx([np.pi, -np.pi])
    assert circle.kwargs["rollangle"] == pytest.approx(2 * np.pi)
    assert "radius" not in circle.kwargs
    # the rulebook says pulled from upright at the bottom and from inverted at the top, pushed
    # in the other two: the loop goes up from the bottom and down from the top
    pulled = (entry["entry_attitude"] == "upright") == ("bottom" in entry["description"])
    assert (circle.args[0] > 0) == pulled
    # the corners of the diamond are 1/8, 1/4, 1/4, 1/4, 1/8 in one sense, with a radius of
    # their own, and a half roll in each leg
    corners = [e for e in rest if e.kind == "loop"]
    assert [round(abs(e.args[0]) / (np.pi / 4)) for e in corners] == [1, 2, 2, 2, 1]
    assert all(e.kwargs["radius"] == "diamond_radius" for e in corners)
    legs = [e for e in rest if e.kind == "roll"]
    assert len(legs) == 4
    assert all(e.args[0] == pytest.approx(np.pi) and e.kwargs["padded"] for e in legs)
    assert fig.ndmps["diamond_radius"].like == "loop_radius"


@pytest.mark.parametrize("number", ["30.1", "30.2", "30.3", "30.4"])
def test_g30_diamond_in_a_loop_radius_is_its_own_parameter_and_the_figure_closes(number, mb):
    entry = FIXTURE_BY_NUMBER[number]
    fig, _, states = _g2730_template(number, mb)
    assert float(states.pos.z[-1] - states.pos.z[0]) == pytest.approx(0, abs=1e-6)
    assert float(states.pos.y[-1] - states.pos.y[0]) == pytest.approx(0, abs=1e-6)
    assert _g2730_exit_attitude(states) == entry["exit_attitude"]
    # the radii are separate parameters: changing the diamond's leaves the loop's alone
    small = _g2730_template(number, mb, diamond_radius=15.0)
    large = _g2730_template(number, mb, diamond_radius=35.0)

    def circle_end(templates):
        last = [name for name in templates if name.startswith("e_0")][-1]
        return float(templates[last].pos.x[-1]), float(templates[last].pos.z[-1])

    assert circle_end(small[1]) == pytest.approx(circle_end(large[1]))
    # the diamond is bigger with bigger corners
    assert float(np.max(np.abs(small[2].pos.z))) != pytest.approx(float(np.max(np.abs(large[2].pos.z))), abs=1)


def test_g30_diamond_in_a_loop_is_strict():
    base = FIXTURE_BY_NUMBER["30.1"]["description"]
    for text, words in (
        (base.replace("two opposite integrated half-rolls", "integrated half-rolls"), "loop with two opposite"),
        (base.replace("half-roll in each leg", "full roll in each leg"), "square loop"),
        (base.replace("From bottom upright", "From bottom"), "from"),
        (base.replace("Exit upright", "Exit inverted"), "exits upright"),
    ):
        with pytest.raises(F3AParseError, match=words):
            parse_f3a_description(text)


def test_g2730_names_do_not_change_other_families():
    # the figure names of groups 27-30 are only read with their step text
    assert parse_f3a_description("Square loop on corner").info.name.lower().startswith("square loop")
    with pytest.raises(F3AParseError, match="no figure family"):
        parse_f3a_description("Infinite loop")


# ---------------------------------------------------------------- groups L and M


def _lm_texts():
    return [e for e in FIXTURE if e["group"] in ("L", "M")]


def _lm_loops(fig):
    return [e for e in fig.elements if e.kind == "loop"]


def _lm_stated(entry):
    """The pulls (True) and pushes (False) in brackets; None where alternatives differ."""
    import re

    group = re.search(r"\(((?:pull|push)[^)]*)\)", entry["description"]).group(1)
    triples = [[w.strip() == "pull" for w in alt.split(",")] for alt in group.split(", or ")]
    return [triples[0][i] if all(t[i] == triples[0][i] for t in triples) else None for i in range(3)]


@pytest.mark.parametrize(
    "entry",
    [e for e in _lm_texts() if "roll options" not in e["description"]],
    ids=lambda e: e["number"],
)
def test_lm_loops_are_pulled_or_pushed_as_stated(entry):
    from pyolan.f3a.parser import ERRATA

    fig = parse_f3a_description(entry["description"], entry["number"], entry["k"])
    first, middle, last = _lm_loops(fig)
    # an errata entry is pulled or pushed as its corrected words say
    stated = _lm_stated({"description": ERRATA.get(entry["number"], (None, entry["description"]))[1]})
    # a positive loop angle is a pull
    assert (first.args[0] > 0) == stated[0]
    assert (last.args[0] > 0) == stated[2]
    if "ke" in middle.kwargs:
        # between two quarter-rolled lines the half loop is flown in knife-edge flight
        assert middle.kwargs["ke"] == pytest.approx(np.pi / 2)
        assert "roll_option" in fig.ndmps
    else:
        assert stated[1] is None or (middle.args[0] > 0) == stated[1]


def test_lm_humpty_bump_loops_go_one_way_and_back():
    up = parse_f3a_description("L.1 Humpty bump (pull, pull, push) half roll up, 2/4pt roll down (K3)")
    assert [e.args[0] for e in _lm_loops(up)] == pytest.approx([np.pi / 2, np.pi, -np.pi / 2])
    # from the top it is the mirror image, down first
    down = parse_f3a_description("M.1 Humpty bump from top, half roll down (push, push, push) (K3)")
    assert [e.args[0] for e in _lm_loops(down)] == pytest.approx([-np.pi / 2, -np.pi, -np.pi / 2])
    # M.1 only rolls the down line, the up line is a plain line
    assert [e.kind for e in down.elements] == ["loop", "roll", "loop", "line", "loop"]


@pytest.mark.parametrize(
    "text",
    [
        "L.1 Humpty bump (push, pull, push) half roll up, 2/4pt roll down (K3)",
        "L.1 Humpty bump (pull, push, push) half roll up, 2/4pt roll down (K3)",
        "L.1 Humpty bump (pull, pull, pull) half roll up, 2/4pt roll down (K3)",
        "L.2 Humpty bump (pull, pull, push) half roll up, 2/4pt roll down, inverted entry (K3)",
        "M.1 Humpty bump from top, half roll down (pull, push, push) (K3)",
        "M.3 Humpty bump from top, 2/4pt roll down, half roll up (push, push, push) (K3)",
    ],
)
def test_lm_wrong_pulls_and_pushes_are_an_error(text):
    with pytest.raises(F3AParseError, match="pulled|pushed|exits"):
        parse_f3a_description(text)


def test_lm_pulls_and_rolls_are_required():
    with pytest.raises(F3AParseError, match="missing"):
        parse_f3a_description("L.1 Humpty bump half roll up, 2/4pt roll down (K3)")
    with pytest.raises(F3AParseError, match="expected a roll"):
        parse_f3a_description("L.1 Humpty bump (pull, pull, push) half roll up (K3)")
    with pytest.raises(F3AParseError, match="unexpected"):
        parse_f3a_description("M.1 Humpty bump from top, half roll up, 2/4pt roll up (push, push, push) (K3)")


def test_lm_exit_inverted_is_checked():
    ok = parse_f3a_description("M.10 Humpty bump from top, 1/4 roll down, 3/4 roll up, inverted exit (push, push, pull) (K3)")
    assert ok.info.end.orientation == p.Orientation.INVERTED
    with pytest.raises(F3AParseError, match="exits"):
        parse_f3a_description("M.10 Humpty bump from top, 1/4 roll down, 3/4 roll up, inverted exit (push, push, push) (K3)")


def test_lm_roll_options_are_two_figures():
    option = parse_f3a_description("L.11 Humpty bump with roll options, (half roll up or 1/4 roll up and down) (K2)")
    assert isinstance(option, a.Option)
    half, quarters = option.figures
    assert [e.kind for e in half.elements] == ["loop", "roll", "loop", "line", "loop"]
    assert [e.kind for e in quarters.elements] == ["loop", "roll", "loop", "roll", "loop"]
    assert not half.ndmps and "roll_option" in quarters.ndmps
    # the 1/4 rolls make the half loop a knife-edge loop
    assert "ke" in _lm_loops(quarters)[1].kwargs and "ke" not in _lm_loops(half)[1].kwargs
    inverted = parse_f3a_description("L.12 Humpty bump with roll options, (half roll up or 1/4 roll up and down) inverted entry (K2)")
    assert len(inverted.figures) == 2


def test_lm_group_18_is_unchanged_by_the_turnaround_builder():
    fig = parse_f3a_description("18.1 Humpty bump, half roll up, 2/4pt roll down (K4)")
    assert fig.info.position == p.Position.CENTRE
    assert [abs(e.args[0]) for e in _lm_loops(fig)] == pytest.approx([np.pi / 2, np.pi, np.pi / 2])


def test_l7_stated_last_push_contradicts_the_drawing_exit(monkeypatch):
    # L.7 "(pull, pull, push, or pull, push, push) 1/4 roll up, 3/4 roll down": a last push
    # leaves the aircraft inverted, but the drawing says upright -> upright (L.8, with the
    # mirror entry, ends "pull" and upright). With its number the ERRATA correction (last
    # pull) is used; the words alone are parsed as written.
    entry = FIXTURE_BY_NUMBER["L.7"]
    assert entry["exit_attitude"] == "upright"
    with monkeypatch.context() as m:
        m.setattr("pyolan.f3a.parser.ERRATA", {})
        as_written = parse_f3a_description(entry["description"], entry["number"], entry["k"])
    assert as_written.info.end.orientation == p.Orientation.INVERTED
    fig = parse_f3a_description(entry["description"], entry["number"], entry["k"])
    assert fig.info.end.orientation == p.Orientation.UPRIGHT


def test_errata_apply_only_to_the_catalogued_words():
    from pyolan.f3a.parser import ERRATA

    for number, (catalogued, corrected) in ERRATA.items():
        assert FIXTURE_BY_NUMBER[number]["description"] == catalogued
        assert parse_f3a_description(catalogued, number).info.name == corrected
        # a corrected catalogue passes through unchanged
        assert parse_f3a_description(corrected, number).info.name == corrected
    # another entry's words under an errata number are not replaced
    p2 = FIXTURE_BY_NUMBER["P.2"]["description"]
    assert parse_f3a_description("L.8 " + FIXTURE_BY_NUMBER["L.8"]["description"]).info.name != ERRATA["L.7"][1]
    assert parse_f3a_description(p2, "P.2").info.name == p2


def test_slow_roll_is_one_centred_roll():
    for text, attitude in (("23.15 Slow roll (K3)", p.Orientation.UPRIGHT),
                           ("23.16 Slow roll, inverted entry (K3)", p.Orientation.INVERTED)):
        fig = parse_f3a_description(text)
        assert [e.kind for e in fig.elements] == ["roll"]
        assert fig.elements[0].args == pytest.approx([2 * np.pi])
        assert fig.info.start.orientation == fig.info.end.orientation == attitude


# ---------------------------------------------------------------- group K


def _k_exit_minus_entry(fig, radius=20.0, line=1000.0, option=0):
    """The template's exit height minus its entry height in metres, with lines long
    enough that no roll lengthens its line."""
    mdef = mb_for_k().create_mdef(fig)
    mdef.mps.data["loop_radius"].defaul = radius
    mdef.mps.data["line_length"].defaul = line
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = option
    entry = fig.info.start.orientation
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(entry, 0, p.Heading.RTOL), g.P0())
    )
    tp = State.stack(templates, "element")
    return float(tp.pos.z[-1] - tp.pos.z[0])


def mb_for_k():
    from tuning.builders import load_builder

    return load_builder("f3a")


def _down_line_length(fig):
    """The line_length expression of the padded roll on the 45 degree down line."""
    return [e.kwargs.get("line_length") for e in fig.elements if e.kind == "roll"]


def test_k_half_loop_direction_is_an_option_one_figure_per_direction():
    # drawn: K.1-K.8 loop down (outside for an upright pilot), K.9-K.32 up; the
    # other direction is the second figure
    plain = parse_f3a_description("K.1 45 degree up, 2/4pt roll, half loop (inside or outside), full roll down (K3)")
    assert isinstance(plain, a.Option) and len(plain.figures) == 2
    assert [e.kind for e in plain.figures[0].elements] == ["loop", "roll", "loop", "roll", "loop"]
    assert [np.sign(f.elements[2].args[0]) for f in plain.figures] == [1, -1]
    ke = parse_f3a_description(
        "K.9 45 degree up-line from upright, 1/4 roll, knife-edge half loop (up or down), "
        "three consecutive 1/4 rolls down, exit upright (K4)"
    )
    assert [e.kind for e in ke.figures[0].elements] == ["loop", "roll", "loop", "roll", "loop"]


K_PUSHED = "(line_length-(2*loop_radius))"
K_PULLED = "(line_length+(2*loop_radius))"


def test_k_down_line_closes_the_figure_with_a_length_of_its_own():
    # decided 2026-11-20 (A4 review): the figure finishes at its entry height, the
    # lines need not match. The half loop shifts the down line by 2 radii, so the down
    # line is 2 radii longer after the loop that goes up and 2 shorter after the one
    # that goes down. Only the padded roll on the down line carries the expression.
    plain = parse_f3a_description("K.1 45 degree up, 2/4pt roll, half loop (inside or outside), full roll down (K3)")
    down, up = plain.figures  # K.1 draws the loop down first
    assert _down_line_length(down) == [None, K_PUSHED]
    assert _down_line_length(up) == [None, K_PULLED]
    ke = parse_f3a_description(
        "K.9 45 degree up-line from upright, 1/4 roll, knife-edge half loop (up or down), "
        "three consecutive 1/4 rolls down, exit upright (K4)"
    )
    # K.9 draws the loop up first (a knife-edge loop's size is a roll_option value)
    assert [_down_line_length(f) for f in ke.figures] == [[None, K_PULLED], [None, K_PUSHED]]
    # the lengths agree in the units used for the heights, so entry and exit are one level
    for fig in (*plain.figures, *ke.figures):
        assert fig.info.start.height == fig.info.end.height == p.Height.BTM


@pytest.mark.parametrize("number", ["K.1", "K.3", "K.5", "K.9", "K.10", "K.12", "K.17", "K.24"])
def test_k_figures_finish_at_their_entry_height(number):
    entry = FIXTURE_BY_NUMBER[number]
    parsed = parse_f3a_description(entry["description"], number, entry["k"])
    for fig in parsed.figures:
        for option in (0, 1):
            for radius in (20.0, 55.0, 90.0):
                assert _k_exit_minus_entry(fig, radius, 1000.0, option) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("number", ["K.7", "K.8", "K.26", "K.31"])
def test_k_snap_on_the_down_line_leaves_a_size_independent_residual(number):
    # a snap's path is not exactly its length in the builder's padding, so the closure is
    # off by a couple of metres that do not change with the radius or the line length;
    # the layout takes them up with the snap rate
    entry = FIXTURE_BY_NUMBER[number]
    parsed = parse_f3a_description(entry["description"], number, entry["k"])
    for fig in parsed.figures:
        residuals = [_k_exit_minus_entry(fig, r, line) for r, line in ((20.0, 1000.0), (55.0, 400.0), (90.0, 1000.0))]
        assert residuals == pytest.approx([residuals[0]] * 3, abs=1e-6)
        assert abs(residuals[0]) < 2.5


def test_k_figures_have_a_roll_on_each_45_degree_line_and_no_extra_lines():
    # the rolls are centred on their lines, which are the 45 degree lines
    # (no roll starts or ends the figure, so there is no roll_line_length)
    for text in (
        "K.3 45 degree up, 2/2pt roll, half loop (inside or outside), 2/4pt roll down (K3)",
        "K.7 45 degree up, 2/2pt roll, half loop (inside or outside), full snap roll down (K4)",
        "K.17 45 degree up-line from upright, three consecutive 1/4 rolls, knife-edge half loop (up or down), "
        "1/4 roll down, exit upright (K4)",
    ):
        for fig in parse_f3a_description(text).figures:
            assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "roll", "loop"]
            assert fig.elements[0].args[0] == pytest.approx(np.pi / 4)
            assert abs(fig.elements[4].args[0]) == pytest.approx(np.pi / 4)
            assert all(e.kwargs.get("padded") for e in fig.elements if e.kind == "roll")
            assert "roll_line_length" not in fig.ndmps


def test_k_knife_edge_rolls_and_half_loop_are_one_mirror_option():
    # the rolls set the knife-edge side and the half loop yaws towards it, so they
    # flip together (one roll_option); the loop goes up or down whatever the exit
    # attitude, which is decided by the second roll against the first
    texts = {
        "K.9": "45 degree up-line from upright, 1/4 roll, knife-edge half loop (up or down), "
        "three consecutive 1/4 rolls down, exit upright (K4)",
        "K.10": "45 degree up-line from upright, 1/4 roll, knife-edge half loop (up or down), "
        "three consecutive 1/4 rolls down, exit inverted (K4)",
        "K.26": "45 degree up-line from upright, 1/4 roll, knife-edge half loop (up or down), "
        "3/4 snap roll down, exit inverted (K5)",
    }
    relative = {}
    for number, text in texts.items():
        figs = parse_f3a_description(f"{number} {text}").figures
        assert len(figs) == 2
        for fig in figs:
            assert list(fig.ndmps) == ["roll_option"]
            values, mirrored = fig.ndmps["roll_option"]
            assert mirrored == pytest.approx([-v for v in values])
            assert abs(values[0]) == pytest.approx(np.pi / 2)  # the 1/4 roll
            assert abs(values[1]) == pytest.approx(np.pi)  # the half loop
            assert sum(abs(v) for v in values[2:]) == pytest.approx(3 * np.pi / 2)  # the 3/4 roll
            loops = [e for e in fig.elements if e.kind == "loop"]
            assert loops[1].kwargs["ke"] == pytest.approx(np.pi / 2)
        assert {np.sign(f.ndmps["roll_option"][0][1]) for f in figs} == {-1, 1}  # up and down
        relative[number] = {np.sign(f.ndmps["roll_option"][0][0] * f.ndmps["roll_option"][0][2]) for f in figs}
        assert len(relative[number]) == 1
    # K.9 and K.10 differ only in the exit attitude: the second roll goes the other
    # way against the first; K.26 exits inverted like K.10
    assert relative["K.9"] != relative["K.10"]
    assert relative["K.26"] == relative["K.10"]


def test_k_rejects_phrases_it_does_not_read():
    base = (
        "K.9 45 degree up-line from upright, 1/4 roll, knife-edge half loop (up or down), "
        "three consecutive 1/4 rolls down"
    )
    with pytest.raises(F3AParseError, match="exit attitude is missing"):
        parse_f3a_description(base)
    with pytest.raises(F3AParseError, match="expected"):
        parse_f3a_description(base.replace("three consecutive 1/4 rolls down", "three consecutive 1/4 rolls") + ", exit upright")
    with pytest.raises(F3AParseError, match="inside or outside"):
        parse_f3a_description("45 degree up, full roll, half loop, full roll down")


def test_k_does_not_change_group_11():
    fig = parse_f3a_description("11.11 45 degree up with full snap roll (K3)")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop"]
    with pytest.raises(F3AParseError, match="expected one roll"):
        parse_f3a_description("45 degree up with full roll, half loop (inside or outside)")


# ---------------------------------------------------------------- group J: top hat turnarounds


def _j_loops(text):
    fig = parse_f3a_description(text)
    return fig, [e for e in fig.elements if e.kind == "loop"]


def test_j_plain_top_hat_has_a_forward_top_line_and_exits_back():
    # J.1-J.10: corners 1/4, -1/4, -1/4, -1/4 (the exit loop turns back), a roll on each vertical
    fig, loops = _j_loops("J.1 Top hat, 3/4 roll up, 1/4 roll down (K2)")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "line", "loop", "roll", "loop"]
    values, mirrored = fig.ndmps["roll_option"]
    assert mirrored == pytest.approx([-v for v in values])
    # the 3/4 roll, the two knife-edge corners, the 1/4 roll: one mirror option
    assert len(values) == 4
    assert loops[0].args[0] == pytest.approx(np.pi / 2)
    assert loops[3].args[0] == pytest.approx(np.pi / 2)
    assert [loops[i].kwargs["ke"] for i in (1, 2)] == [pytest.approx(np.pi / 2)] * 2
    # the second and third corners turn the other way from the first
    assert values[1] == pytest.approx(values[2])


def _j_end_x(text, mb):
    mdef = mb.create_mdef(parse_f3a_description(text))
    if "roll_option" in mdef.mps.data:
        mdef.mps.data["roll_option"].defaul = 0
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    x = State.stack(templates, "element").pos.x
    return float(x[-1] - x[0])


def test_j_the_exit_is_beyond_the_start_only_with_a_forward_top_line(mb):
    # forward top line (J.1): the exit line ends ahead of where the figure started
    # (in the entry direction); back top line (J.11, J.17): behind it
    forward = _j_end_x("J.1 Top hat, 3/4 roll up, 1/4 roll down (K2)", mb)
    back = _j_end_x("J.11 Top hat from top, 3/4 roll down, 3/4pt roll up (K3)", mb)
    back_bottom = _j_end_x(
        "J.26 Top Hat, from upright, 3/4 roll up, 1 1/4 snap roll down, exit upright (K4)", mb
    )
    assert forward * back < 0 and back * back_bottom > 0


def test_j_other_entries_fly_the_top_line_back():
    # J.17: corners 1/4, 1/4, 1/4, -1/4: the top line returns towards where it started
    fig, loops = _j_loops(
        "J.17 Top Hat, from upright, three consecutive 1/4 rolls up, 1 3/4 snap roll down, exit upright (K4)"
    )
    values, _ = fig.ndmps["roll_option"]
    # three quarter rolls, two corners, the 1 3/4 snap
    assert len(values) == 6
    assert abs(values[-1]) / (2 * np.pi) == pytest.approx(1.75)
    assert values[1 + 2] == pytest.approx(values[1 + 3])  # the two corners turn the same way


@pytest.mark.parametrize(
    "text",
    [
        "J.1 Top hat, 3/4 roll up, 1/4 roll down (K2)",
        "J.3 Top hat, 3/4pt roll up, 3/4 roll down (K2)",
        "J.9 Top hat, 1/4 roll up, 1/4 roll down, inverted exit (K2)",
        "J.11 Top hat from top, 3/4 roll down, 3/4pt roll up (K3)",
        "J.13 Top hat from top, 3/4 roll down, 1/4 roll up (K2)",
        "J.17 Top Hat, from upright, three consecutive 1/4 rolls up, 1 3/4 snap roll down, exit upright (K4)",
        "J.34 Top Hat, from upright, 1/2 roll up, snap roll down, exit upright (K3)",
        "J.36 Top Hat, from top upright, 1/2 roll down, snap roll up, exit upright (K3)",
    ],
)
@pytest.mark.parametrize("option", [0, 1])
def test_j_top_hat_finishes_at_its_entry_height_in_both_mirror_options(text, option, mb):
    # a 3/4pt roll and its pads are longer than line_length, so the vertical lines are
    # (1.5*line_length): the figure still finishes where it started (the snap's
    # pads are sized for 15 m and it flies about 17.6, so a snap leaves a few metres)
    mdef = mb.create_mdef(parse_f3a_description(text))
    if "roll_option" in mdef.mps.data:
        mdef.mps.data["roll_option"].defaul = option
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(p.Orientation.UPRIGHT, 0, p.Heading.RTOL), g.P0())
    )
    z = State.stack(templates, "element").pos.z
    assert float(z[-1] - z[0]) == pytest.approx(0, abs=4 if "snap" in text else 1e-6)


def test_j_four_stop_roll_makes_both_vertical_lines_longer():
    fig = parse_f3a_description(
        "J.44 Top Hat from top upright with 2 turn Spin entry, four consecutive 1/4 rolls up, exit inverted (K3)"
    )
    lengths = [e.kwargs.get("length") or e.kwargs.get("line_length") for e in fig.elements if e.kind in ("roll", "line")]
    assert lengths.count("(2*line_length)") == 2


def test_j_exit_is_upright_unless_stated():
    for number, text, exit_ in (
        ("J.1", "Top hat, 3/4 roll up, 1/4 roll down", p.Orientation.UPRIGHT),
        ("J.2", "Top hat, 3/4 roll up, 1/4 roll down, inverted entry", p.Orientation.UPRIGHT),
        ("J.5", "Top hat, 3/4pt roll up, 3/4 pt roll down, inverted exit", p.Orientation.INVERTED),
    ):
        info = parse_f3a_description(text, number, 2).info
        assert info.end.orientation == exit_


def test_j_spin_entry_replaces_the_first_corner():
    fig = parse_f3a_description(
        "J.42 Top Hat from top upright with 2 turn Spin entry, Full Roll up, exit inverted (K3)"
    )
    assert [e.kind for e in fig.elements] == ["spin", "line", "loop", "line", "loop", "roll", "loop"]
    assert fig.ndmps == {}  # a whole number of turns: the builder's reversible spin
    assert [e.args[0] for e in fig.elements if e.kind == "loop"] == pytest.approx([-np.pi / 2, -np.pi / 2, np.pi / 2])


def test_j_quarter_turn_spin_is_one_mirror_option_with_the_knife_edge_corners():
    fig = parse_f3a_description(
        "J.38 Top Hat from top upright with 2 1/4 turn Spin entry, 3/4 Roll up, exit upright (K4)"
    )
    values, mirrored = fig.ndmps["roll_option"]
    assert mirrored == pytest.approx([-v for v in values])
    assert len(values) == 4  # the spin, two knife-edge corners, the 3/4 roll
    assert abs(values[0]) / (2 * np.pi) == pytest.approx(2.25)


@pytest.mark.parametrize(
    "text, words",
    [
        ("J.99 Top hat, 3/4 roll up (K2)", "expected a roll up and a roll down"),
        ("J.99 Top hat, 3/4 roll up, 1/4 roll up (K2)", "unexpected"),
        ("J.99 Top hat, 3/4 roll up, 1/4 roll down, exit upright, exit inverted (K2)", "given twice"),
        ("J.99 Top hat, 1/4 roll up, 1/4 roll down, inverted entry, from upright (K2)", "given twice"),
        ("J.99 Top Hat from top upright with 2 turn Spin entry, four consecutive 1/4 rolls down, exit inverted", "spin entry"),
        ("J.99 Top Hat upright with 2 turn Spin entry, Full Roll up, exit inverted", "spin entry"),
        ("J.99 Top Hat from top upright with 2 turn Spin entry, Full Roll up, exit upright", "exits inverted"),
        ("J.99 Top hat, 3/4 roll up, 3/4 roll down, wiggle", "unexpected"),
    ],
)
def test_j_top_hat_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


def test_j_does_not_change_the_group_17_top_hat():
    fig = parse_f3a_description("17.1 Top hat with 2/4pt rolls (K3)")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "line", "loop", "roll", "loop"]
    assert fig.info.position == p.Position.CENTRE


# ---------------------------------------------------------------- groups P and Q

# The USG descriptions of P.6 and P.12 disagree with their own drawings and metadata:
# P.6's words are P.2's ("from upright") but the drawing starts at the top, and P.12 says
# "from top inverted ... exit upright" where the drawing and metadata are low, inverted to
# inverted (the drawing is P.11's with the other exit, i.e. a 1/4 roll). A corrected
# description is what the import has to use for these two (tested here, not listed in
# implemented_groups.txt because the catalogue text itself does not match). With their
# numbers, the parser's ERRATA table gives these corrections.
PQ_CORRECTED = {
    "P.6": "Vertical 5/8 loop from top upright, snap-roll, roll, exit inverted",
    "P.12": "Vertical 5/8 loop from inverted, 3/4 snap-roll, 1/4 roll, exit inverted",
}


@pytest.mark.parametrize("number", sorted(PQ_CORRECTED))
def test_pq_corrected_descriptions_match_the_drawing(number, mb):
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(PQ_CORRECTED[number], number, entry["k"])
    keys = ("entry_attitude", "exit_attitude", "entry_height", "exit_height", "kind")
    assert _template_metadata(fig, mb, entry["entry_attitude"]) == {k: entry[k] for k in keys}


def test_pq_p_descriptions_that_disagree_with_the_drawing_are_not_corrected_silently(mb):
    # as catalogued, P.6 is P.2 and P.12 starts at the top, so neither matches its drawing
    assert FIXTURE_BY_NUMBER["P.6"]["description"] == FIXTURE_BY_NUMBER["P.2"]["description"]
    p6 = parse_f3a_description(FIXTURE_BY_NUMBER["P.6"]["description"])
    assert p6.info.start.height == p.Height.BTM and FIXTURE_BY_NUMBER["P.6"]["entry_height"] == "high"
    p12 = parse_f3a_description(FIXTURE_BY_NUMBER["P.12"]["description"])
    assert p12.info.start.height == p.Height.TOP and FIXTURE_BY_NUMBER["P.12"]["entry_height"] == "low"


def _pq_template_z(fig, mb, attitude=p.Orientation.UPRIGHT, radius=None):
    mdef = mb.create_mdef(fig)
    if radius is not None:
        mdef.mps.data["loop_radius"].defaul = radius
    for name in mdef.mps.data:
        if name.startswith("roll_option"):
            mdef.mps.data[name].defaul = 0
    templates = mdef.create().create_template(
        g.Transformation(g.Euler(attitude, 0, p.Heading.RTOL), g.P0())
    )
    return State.stack(templates, "element").pos.z


@pytest.mark.parametrize(
    "text",
    [
        "Vertical 5/8 loop from upright, snap-roll, half roll, exit upright (K4)",
        "Vertical 5/8 loop from inverted, snap-roll, roll, exit upright (K4)",
        "Vertical 5/8 loop from top upright, snap-roll, half roll, exit upright (K4)",
        "Vertical 5/8 loop from top inverted, snap-roll, roll, exit upright (K4)",
        "Vertical 5/8 loop from upright, 3/4 snap-roll, 1/4 roll, exit upright (K4)",
        "Vertical 5/8 loop from inverted, 3/4 snap-roll, 1/4 half roll, exit upright (K4)",
    ],
)
@pytest.mark.parametrize("radius", [None, 45])
def test_pq_vertical_5_8_loop_finishes_at_its_entry_height(text, radius, mb):
    # the snap flies about 2.6 m further than its pads are sized for (known builder
    # limitation), so the exit is up to that far from the entry
    z = _pq_template_z(parse_f3a_description(text), mb, radius=radius)
    assert z[-1] - z[0] == pytest.approx(0, abs=3.0)


def test_pq_vertical_5_8_loop_shape():
    # entry 1/4 loop, snap on the vertical, 5/8 loop, roll on the 45 degree line, 3/8 loop
    fig = parse_f3a_description("P.1 Vertical 5/8 loop from upright, snap-roll, half roll, exit upright (K4)")
    assert [e.kind for e in fig.elements] == ["loop", "roll", "loop", "roll", "loop"]
    loops = [e.args[0] for e in fig.elements if e.kind == "loop"]
    assert loops == pytest.approx([np.pi / 2, 5 * np.pi / 4, 3 * np.pi / 4])
    assert [e.kwargs["rolltypes"] for e in fig.elements if e.kind == "roll"] == ["snap", "roll"]
    # the 3/8 loop goes the other way after a full roll (pushed, exit inverted)
    full = parse_f3a_description("P.2 Vertical 5/8 loop from upright, snap-roll, roll, exit inverted (K4)")
    assert [e.args[0] for e in full.elements if e.kind == "loop"] == pytest.approx(
        [np.pi / 2, 5 * np.pi / 4, -3 * np.pi / 4]
    )
    # from top everything is mirrored in the horizontal
    top = parse_f3a_description("P.5 Vertical 5/8 loop from top upright, snap-roll, half roll, exit upright (K4)")
    assert [e.args[0] for e in top.elements if e.kind == "loop"] == pytest.approx(
        [-np.pi / 2, -5 * np.pi / 4, -3 * np.pi / 4]
    )
    assert fig.ndmps == {} and top.ndmps == {}  # roll directions are the pilot's choice


@pytest.mark.parametrize(
    "text",
    [
        "Vertical 5/8 loop from upright, 3/4 snap-roll, 1/4 roll, exit upright (K4)",
        "Vertical 5/8 loop from upright, 3/4 snap-roll, 1/4 half roll, exit inverted (K4)",
        "Vertical 5/8 loop from inverted, 3/4 snap-roll, 1/4 half roll, exit upright (K4)",
    ],
)
def test_pq_vertical_5_8_loop_with_a_3_4_snap_is_one_knife_edge_mirror_option(text):
    # the snap, the knife-edge loop and the quarter roll go together: the valid signs
    # of the two free rolls are exactly the mirror pair
    fig = parse_f3a_description(text)
    values, mirrored = fig.ndmps["roll_option"]
    assert mirrored == pytest.approx([-v for v in values])
    assert len(values) == 3
    assert abs(values[0]) / (2 * np.pi) == pytest.approx(0.75)  # the snap
    assert abs(values[1]) / (2 * np.pi) == pytest.approx(5 / 8)  # the knife-edge loop
    assert abs(values[2]) / (2 * np.pi) == pytest.approx(0.25)  # the quarter roll
    assert [e.kwargs.get("ke") for e in fig.elements if e.kind == "loop"][1] == pytest.approx(np.pi / 2)


@pytest.mark.parametrize(
    "text, words",
    [
        ("P.99 Vertical 5/8 loop from upright, roll, half roll, exit upright", "expected a snap"),
        ("P.99 Vertical 5/8 loop from upright, snap-roll, 1/4 roll, exit upright", "wings level"),
        ("P.99 Vertical 5/8 loop from upright, 3/4 snap-roll, half roll, exit upright", "wings level"),
        ("P.99 Vertical 5/8 loop from upright, snap-roll, half roll, exit inverted", "exits upright"),
        ("P.99 Vertical 5/8 loop from upright, snap-roll, roll, exit upright", "exits inverted"),
        ("P.99 Vertical 5/8 loop from upright, snap-roll, roll", "exit attitude is missing"),
        ("P.99 Vertical 5/8 loop from middle upright, snap-roll, roll, exit inverted", "not supported"),
        ("P.99 Vertical 5/8 loop from upright, snap-roll, roll, exit inverted, wiggle", "unexpected"),
    ],
)
def test_pq_vertical_5_8_loop_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)


def test_pq_almost_8_is_three_half_loops_of_one_radius(mb):
    text = (
        "Q.1 Almost 8. From bottom upright, half pulled loop with roll integrated, pushed half "
        "loop with roll integrated, pushed half loop with roll integrated, exit middle inverted. (K5)"
    )
    fig = parse_f3a_description(text)
    loops = [e for e in fig.elements]
    assert [e.kind for e in loops] == ["loop"] * 3
    assert [e.args[0] for e in loops] == pytest.approx([np.pi, -np.pi, -np.pi])
    # a roll is integrated through each half loop
    for e in loops:
        assert e.kwargs["rolls"] == pytest.approx(2 * np.pi)
        assert e.kwargs["rollangle"] == pytest.approx(np.pi)
    # the figure is four radii high, the entry at the bottom and the exit in the middle
    z = _pq_template_z(fig, mb)
    radius = mb.mps.data["loop_radius"].defaul
    assert z[-1] - z[0] == pytest.approx(2 * radius, abs=1e-6)
    assert max(z) - min(z) == pytest.approx(4 * radius, abs=1e-6)


@pytest.mark.parametrize(
    "number, signs",
    [
        ("Q.1", [1, -1, -1]),
        ("Q.2", [1, -1, 1]),
        ("Q.3", [-1, 1, 1]),
        ("Q.4", [-1, 1, -1]),
        ("Q.5", [-1, -1, 1]),
        ("Q.6", [1, 1, 1]),
        ("Q.7", [1, 1, -1]),
        ("Q.8", [-1, -1, -1]),
    ],
)
def test_pq_almost_8_loop_directions_follow_pull_and_push(number, signs):
    entry = FIXTURE_BY_NUMBER[number]
    fig = parse_f3a_description(entry["description"], number, entry["k"])
    # an element's angle is positive when pulled and negative when pushed, whichever
    # way the half loop turns in the plane (the template shapes are reviewed in the sheets)
    assert [np.sign(e.args[0]) for e in fig.elements] == signs
    assert fig.ndmps == {}  # roll directions are the pilot's choice


def test_pq_almost_8_half_roll_is_integrated_in_the_stated_half_loop():
    fig = parse_f3a_description(FIXTURE_BY_NUMBER["Q.2"]["description"])
    assert ["rolls" in e.kwargs for e in fig.elements] == [False, True, False]
    assert fig.elements[1].kwargs["rolls"] == pytest.approx(np.pi)
    assert fig.elements[1].kwargs["rollangle"] == pytest.approx(np.pi)


@pytest.mark.parametrize(
    "text, words",
    [
        # the height words must be the figure's
        ("Almost 8. From middle upright, half pulled loop, pushed half loop, pushed half loop, exit middle inverted", "from middle"),
        ("Almost 8. From bottom upright, half pulled loop, pushed half loop, pushed half loop, exit top inverted", "exit top"),
        # the words must fit the attitude: a push from upright goes down, not up from the bottom
        ("Almost 8. From bottom upright, half pushed loop, pushed half loop, pushed half loop, exit middle inverted", "from bottom"),
        ("Almost 8. From bottom upright, half pulled loop, pushed half loop, exit middle inverted", "three half loops"),
        ("Almost 8. From bottom upright, half pulled loop, pushed half loop, pushed half loop, exit middle upright", "exits inverted"),
        ("Almost 8. From bottom upright, half pulled loop, roll integrated, roll integrated, pushed half loop, pushed half loop, exit middle inverted", "two rolls"),
        ("Almost 8. From bottom upright, half pulled loop, wiggle, pushed half loop, pushed half loop, exit middle inverted", "unexpected"),
        ("Almost 8. upright, half pulled loop, pushed half loop, pushed half loop, exit middle inverted", "from bottom"),
    ],
)
def test_pq_almost_8_is_strict(text, words):
    with pytest.raises(F3AParseError, match=words):
        parse_f3a_description(text)
