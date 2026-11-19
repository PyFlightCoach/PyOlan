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
# A cobra roll from top is a V: its entry height is "middle" in the drawings but
# can be middle or high depending on the manoeuvre before it (decided
# 2026-11-18), and the template measures heights against the figure's own range.
# Entry and exit heights are not compared for these.
FLEXIBLE_START_HEIGHT = {f"08.{n}" for n in range(5, 11)}
# The USG text layer gives 14.21 "Height : low->low" but its drawing (like 14.22's,
# whose description is the same words) has the entry and exit at the waist of
# the knife-edge eight, "middle entry and exit": a typo in the USG metadata.
FIXTURE_HEIGHT_TYPO = {"14.21": "middle"}


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


def _template_metadata(fig, mb, entry: str) -> dict:
    mdef = mb.create_mdef(fig)
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


@pytest.mark.parametrize("entry", _cases())
def test_matches_usg_drawing(entry, mb):
    parsed = parse_f3a_description(entry["description"], entry["number"], entry["k"])
    figures = parsed.figures if isinstance(parsed, a.Option) else [parsed]
    keys = ("entry_attitude", "exit_attitude", "entry_height", "exit_height", "kind")
    expected = {k: entry[k] for k in keys}
    if entry["number"] in FLEXIBLE_START_HEIGHT:
        expected["entry_height"] = expected["exit_height"] = "high"
        assert entry["entry_height"] == entry["exit_height"] == "middle"
    if entry["number"] in FIXTURE_HEIGHT_TYPO:
        assert entry["entry_height"] == entry["exit_height"] == "low"
        expected["entry_height"] = expected["exit_height"] = FIXTURE_HEIGHT_TYPO[entry["number"]]
    position = p.Position.CENTRE if entry["kind"] == "centre" else p.Position.END
    for fig in figures:
        assert fig.info.k == entry["k"]
        assert fig.info.short_name == entry["number"]
        assert fig.info.position == position
        assert _template_metadata(fig, mb, entry["entry_attitude"]) == expected


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
