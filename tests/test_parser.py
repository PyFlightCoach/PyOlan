import json
from pathlib import Path

import geometry as g
import numpy as np
import pytest
from flightanalysis.builders.manbuilder import ManBuilder
from flightdata import State
from pytest import approx, fixture
from schemas.positioning import Direction, Heading
from tuning.builders import load_builder

from pyolan.figure_parser import OlanFig
from pyolan.errors import OlanParseError
from pyolan.parser import ParsedOlanFig, parse_olan


@fixture(scope="session")
def mb() -> ManBuilder:
    return load_builder("IAC", category="unlimited")

def test_entry_direction(mb: ManBuilder):
    ofigs = parse_olan("13% -``5if```,4ao(,1),22+`", mb)
    assert ofigs[0].aresti.info.start.direction == Direction.UPWIND


def test_parse_olan_sets_exit_direction(mb: ManBuilder):
    upwind = parse_olan("d", mb)[0]
    downwind = parse_olan("ed v", mb)[0]

    assert upwind.aresti.info.start.direction == Direction.UPWIND
    assert upwind.aresti.info.end.direction == Direction.UPWIND
    assert downwind.aresti.info.start.direction == Direction.DOWNWIND
    assert downwind.aresti.info.end.direction == Direction.DOWNWIND


@pytest.mark.parametrize(
    ("olan", "expected_start", "expected_end"),
    [
        (
            "(-2,0) ``-5is...''iBb(``````)......'8'",
            Direction.UPWIND,
            Direction.DOWNWIND,
        ),
        (
            "ed (-2,0) ``-5is...''iBb(``````)......'8'",
            Direction.DOWNWIND,
            Direction.UPWIND,
        ),
        (
            ">(-2,0) ``-5is...''iBb(``````)......'8'",
            Direction.UPWIND,
            Direction.DOWNWIND,
        ),
    ],
)
def test_turnable_figure_direction_selection(
    mb: ManBuilder, olan: str, expected_start: Direction, expected_end: Direction
):
    figure = parse_olan(olan, mb)[0]

    assert figure.aresti.info.start.direction == expected_start
    assert figure.aresti.info.end.direction == expected_end


def test_create_unl_loop_definition(mb: ManBuilder):

    ofig: ParsedOlanFig = parse_olan("`+o34;5f+`", mb)[0]

    pass
    #assert "point_length" in ofig.definition.mps.data.keys()


def test_imac_sportsman_2025(mb: ManBuilder):
    oseq = parse_olan(
        "/d'1 5% 2a,f (-3,6) 4h4^> p(2)...' dq 4% 2b.''1.''+``` (-13,0) 3% ~2g~ (2,0) 3% iv```6s.....'' 22y````1.. (-3,0) 8% `24'zt`8''",
        mb,
    )
    assert len(oseq) == 10


def test_imac_inter_2025(mb: ManBuilder):
    oseq = parse_olan(
        "d'f 5% 44a,if- (-3,6) -4h2,4-^> -,ify...''22 (-1,0) -2% 1dq1 1j1> 3% ``1,24pb...34..+++ 3% ~`1,48``g~ (5,0) 3% ```9s....'ikz----~~ /-22iy2",
        mb,
    )
    assert len(oseq) == 10


def test_turn(mb: ManBuilder):
    fig: ParsedOlanFig = parse_olan("4j", mb)[0]

    assert [e.kind for e in fig.aresti.elements] == ["roll", "loop", "roll"]
    assert fig.aresti.elements[0].args == [["roll_option[0]"]]
    assert fig.aresti.elements[1].args == [approx(2 * np.pi)]
    assert fig.aresti.elements[1].kwargs["ke"] == "roll_option[1]"
    assert fig.aresti.elements[2].args == [["roll_option[2]"]]
    bank = [np.radians(60), np.radians(30), np.radians(-60)]
    assert fig.aresti.ndmps == {
        "roll_option": [approx(bank), approx([-v for v in bank])]
    }
    assert fig.aresti.info.k == 6

    option = fig.definition.mps.data["roll_option"]
    assert [str(c) for c in option.collectors] == [
        "e_0_0.e_0_0.roll.0",
        "e_1.e_1.ke.1",
        "e_2_0.e_2_0.roll.2",
    ]


@pytest.mark.parametrize("code, exit_bearings", [
    ("j", [np.pi / 2, -np.pi / 2]),
    ("2j", [np.pi, np.pi]),
    ("4j", [0, 0]),
])
def test_turn_options_build_mirrored_level_turns(
    mb: ManBuilder, code: str, exit_bearings: list[float]
):
    mdef = parse_olan(code, mb)[0].definition
    itrans = g.Transformation(g.Euler(0, 0, 0), g.P0())

    # option 0 is the way OpenAero draws the turn (C5), so the order is not fixed
    sides, bearings = [], []
    for index in range(len(exit_bearings)):
        mdef.mps.data["roll_option"].defaul = index
        tp = State.stack(mdef.create().create_template(itrans), "element")

        bearings.append(tp.att.bearing()[-1])
        assert np.abs(tp.pos.z).max() == approx(0, abs=1e-6)
        # exits wings level with the same attitude as the entry
        assert tp.att[-1].transform_point(g.PZ()).z[0] == approx(
            tp.att[0].transform_point(g.PZ()).z[0]
        )
        sides.append(np.sign(tp.pos.y[len(tp) // 2]))

    assert sorted(sides) == [-1, 1]
    for exit_bearing in exit_bearings:
        assert min(abs(np.cos(b - exit_bearing) - 1) for b in bearings) < 1e-9


@pytest.mark.parametrize(
    "olan, index, exit",
    # F4: OpenAero draws these quarter turns out of the box (wind from the right)
    [("1j1", 0, Heading.INTOOUT), ("eu 3j", 0, Heading.INTOOUT), ("o 1j1 o", 1, Heading.INTOOUT)],
)
def test_turn_option_0_is_openaero_direction(mb: ManBuilder, olan, index, exit):
    fig = parse_olan(olan, mb, Heading.RTOL)[index]
    assert Heading.infer(fig.template.att.bearing()[-1]) == exit
    assert fig.definition.mps.data["roll_option"].defaul == 0


def test_rolling_circle_preserves_turn_and_roll_constraints(mb: ManBuilder):
    fig: ParsedOlanFig = parse_olan("4joi4", mb)[0]
    element = fig.aresti.elements[0]

    assert element.kind == "loop"
    assert element.args == [approx(2 * np.pi)]
    assert element.kwargs["ke"] == approx(np.pi / 2)
    assert element.kwargs["rolls"] == [
        approx(-2 * np.pi),
        approx(2 * np.pi),
        approx(-2 * np.pi),
        approx(2 * np.pi),
    ]
    assert fig.aresti.info.k == 46


def test_rolling_circle_exposes_both_turn_and_roll_options(mb: ManBuilder):
    fig = parse_olan("(5,0) 4% 3jo3", mb)[0]

    assert fig.aresti.ndmps == {
        "roll_option": [
            [3 * np.pi / 2, -6 * np.pi],
            [-3 * np.pi / 2, 6 * np.pi],
        ]
    }
    loop = fig.aresti.elements[0]
    assert loop.args == ["roll_option[0]"]
    assert loop.kwargs["rolls"] == "roll_option[1]"


def test_parse_olan_preserves_open_aero_k_factor(mb: ManBuilder):
    fig = parse_olan("d_-", mb)[0]

    assert fig.aresti.info.k == 9
    assert fig.definition.info.k == 9


def test_parse_olan_matches_open_aero_compound_figure_k_factors(mb: ManBuilder):
    olan = (
        "3% /+`,2ifpbb(````````,34...)'22`-~~ "
        "(-2,-1) 4% ``-````,5is,2ib````,24'-```` "
        "7% `-''if..in(```3,34.)''-~ (1,0) "
        "2% -```2ac(....',\"|\"32.....')-` "
        "2% -`,5,\"|\"34p(22).',24....''+++~ (3,0) "
        '"@C" 5% \',9m6f,48---~~ [1,0] '
        "6% /-''ita'',3if.+````` 5% ,22b.'',3f+++ "
        '3% \'\',22m2if "@E" 3% /``+3joi3+'
    )

    figures = parse_olan(olan, mb)

    assert [figure.aresti.info.k for figure in figures] == [
        61, 32, 56, 31, 43, 39, 30, 37, 30, 36
    ]


def test_parse_olan_does_not_link_rolls_that_keep_the_exit_direction(mb: ManBuilder):
    # a full roll does not change the exit direction, so it keeps its own combo
    fig = parse_olan("d1", mb)[0]

    assert fig.aresti.ndmps == {}
    assert "roll_option" not in fig.definition.mps.data


def test_parse_olan_omits_empty_roll_options(mb: ManBuilder):
    fig = parse_olan("+o_+", mb)[0]

    assert fig.aresti.ndmps == {}


def test_parse_olan_creates_structural_aresti_elements(mb: ManBuilder):
    cases = [
        ("o", ["loop"], [2 * np.pi]),
        ("d", ["loop", "line", "loop"], [np.pi / 4, -np.pi / 4]),
        ("h", ["loop", "line", "stallturn", "line", "loop"], [np.pi / 2, np.pi / 2]),
        ("ta", ["loop", "line", "tailslide", "line", "loop"], [np.pi / 2, np.pi / 2]),
    ]

    for code, kinds, loop_angles in cases:
        elements = parse_olan(code, mb)[0].aresti.elements

        assert [element.kind for element in elements] == kinds
        assert [
            element.args[0]
            for element in elements
            if element.kind == "loop"
        ] == loop_angles


def test_figure_n_ends_on_horizontal_line(mb: ManBuilder):
    fig = parse_olan("7% `-''if..in(```3,34.)''-~", mb)[0]

    assert [element.kind for element in fig.aresti.elements] == [
        "loop",
        "roll",
        "loop",
        "roll",
        "loop",
        "line",
        "loop",
    ]
    assert [
        element.args[0]
        for element in fig.aresti.elements
        if element.kind == "loop"
    ] == [
        approx(np.pi / 2),
        approx(3 * np.pi / 4),
        approx(-3 * np.pi / 4),
        approx(-np.pi / 2),
    ]
    assert fig.aresti.elements[-1].args == [approx(-np.pi / 2)]
    assert fig.aresti.elements[3].kwargs["rolltypes"] == "roll"
    assert np.sin(fig.template.att.bearing()[-1]) == approx(0)


def test_spin_following_roll_has_equal_padding_lines(mb: ManBuilder):
    fig = parse_olan("(-2,-1) 4% ``-````,5is,2ib````,24'-````", mb)[0]

    assert fig.aresti.elements[0].kind == "spin"
    assert fig.aresti.elements[1].kind == "roll"
    assert fig.aresti.elements[1].kwargs["padded"] is True

    padded_lines = [
        element
        for element in fig.definition.eds
        if element.name in {"e_1_pad1", "e_1_pad2"}
    ]
    assert [element.name for element in padded_lines] == ["e_1_pad1", "e_1_pad2"]
    assert padded_lines[0].props["length"] == padded_lines[1].props["length"]


def test_tailslide(mb: ManBuilder):
    fig: ParsedOlanFig = parse_olan("~~.,3ita'3....~>", mb)


def test_iac_unl_2026_n(mb: ManBuilder):
    fig: ParsedOlanFig = parse_olan("7% ``-if....'in(.,3,34...'').....''-~~", mb)[0]
    


    pass

def test_iac_unl_2026(mb: ManBuilder):
    olanstr = (Path(__file__).parent / "test_data" / "iac_unl_2026").read_text()
    figs = parse_olan(olanstr, mb)
    assert len(figs) == 10
    names = [f.aresti.info.short_name for f in figs]
    assert len(set(names)) == len(names)  # all names unique
    pass


def test_iac_adv_2026(mb: ManBuilder):
    
    figs = parse_olan("44c,2 (2,0) 9% m1- (12,0) /~~---.h.....''2f.......+++~~ (-16,0) ~++..''n(.'24...).24.'- (-2,0) -5is...''iBb()......'8' 3% 6m~~ (11,0) 22% ,6fic2- -a3',34+ 6% +8pb3..''+``` 3% 2> `44'm24+~~ (5,0) 4% 3jo3", mb)
    assert len(figs) == 11
    names = [f.aresti.info.short_name for f in figs]
    assert len(set(names)) == len(names)  # all names unique
    pass


def test_splits_two_figs(mb: ManBuilder):
    figs = parse_olan("5;3ifdh22 3,8pn(5f,8)", mb)
    assert len(figs)==2


"5;3ifdh22 3,8pn(5f,8) -3,5ig6if,1 ,5ita3if 42c24,9 44hif ,4,3g32- -,is,24irp,32;f n(22,6),2 2j2"
def test_pn(mb: ManBuilder):
    fig = parse_olan("3,8pn(5f,8)", mb)[0]
    assert fig.short_name == "pushN"


def test_a_figure_openaero_does_not_have_is_refused(mb: ManBuilder):
    with pytest.raises(OlanParseError, match="no catalogue figure"):
        parse_olan("o 1jo", mb)


def test_three_figures_with_the_same_short_name_get_unique_names(mb: ManBuilder):
    figs = parse_olan("j 2j 4j", mb)

    assert [f.short_name for f in figs] == ["turn", "turn2", "turn3"]


# Element names must stay stable: stored segmentation in the database is keyed
# by them, so a rename makes stored analyses re-segment. The snapshot was
# generated before turn options were linked through roll_option (PyOlan 501b3f1).
ELEMENT_NAME_SEQUENCES = {
    **{
        f"turn_{code.rstrip('-')}": code
        # "1jo" was here too, and "1j5" without its exit marker: they are not
        # OpenAero figures, so since C3 they have no K and parse_olan raises for
        # them. "1j5-" has the element names "1j5" had.
        for code in "j 2j 3j 4j 2jo1 3jo3 4joi4 2jio2 1j5-".split()
    },
    "iac_unl_2026": (
        Path(__file__).parent / "test_data" / "iac_unl_2026"
    ).read_text().strip(),
    "iac_mixed": (
        "d'f 5% 44a,if- (-3,6) -4h2,4-^> -,ify...''22 (-1,0) -2% 1dq1 1j1> "
        "3% ``1,24pb...34..+++ 3% ~`1,48``g~ (5,0) 3% ```9s....'ikz----~~ /-22iy2"
    ),
    "imac_example": (
        "o 12% 3> ``+````````2``rc+`````` 4> ',1~~ 2% 7> m2 (8,19) 1% id. 6% "
        "8> h.' 8> ,2'b``,2' 12> v'2' (7,18) `````9s..'ik`` 3% 4> 2a"
    ),
}
ELEMENT_NAMES = json.loads(
    (Path(__file__).parent / "data" / "element_names.json").read_text()
)


@pytest.mark.parametrize(
    "rules, options",
    [("IAC", {"category": "unlimited"}), ("IMAC", {"category": "unlimited"})],
)
def test_element_names_match_snapshot(rules: str, options: dict):
    builder = load_builder(rules, **options)

    names = {
        key: [
            [fig.olan.rawfig, list(fig.definition.eds.data.keys())]
            for fig in parse_olan(olan, builder)
        ]
        for key, olan in ELEMENT_NAME_SEQUENCES.items()
    }

    assert names == ELEMENT_NAMES[rules]


FIXTURES = Path(__file__).parent / "data" / "aresti"
CASE_2 = (
    "3% /+`,2ifpbb(````````,34...)'22`-~~ (-2,-1) 4% ``-````,5is,2ib````,24'-```"
)


def _same(got, want) -> bool:
    """Compare nested args, strings exactly and floats approximately."""
    if isinstance(want, (list, tuple)):
        return len(got) == len(want) and all(_same(g_, w) for g_, w in zip(got, want))
    return got == want if isinstance(want, str) else got == approx(want)


def _exit_bearing(figure: ParsedOlanFig, option: int, itrans: g.Transformation):
    mdef = figure.definition
    mdef.mps.data["roll_option"].defaul = option
    try:
        tp = State.stack(mdef.create().create_template(itrans), "element")
    finally:
        mdef.mps.data["roll_option"].defaul = 0
    return tp.att.bearing()[-1]


def test_spin_and_quarter_rolls_match_corrected_figure(mb: ManBuilder):
    expected = json.loads(
        (FIXTURES / "double_humpty_spin_quarter_rolls.aresti.json").read_text()
    )["figures"][0]
    fig = parse_olan("-5isiBb(1.)8", mb)[0].aresti

    for e, x in zip(fig.elements, expected["elements"]):
        assert (e.kind, e.kwargs) == (x["kind"], x["kwargs"])
        assert _same(e.args, x["args"])
    assert len(fig.elements) == len(expected["elements"])
    assert len(fig.ndmps["roll_option"]) == len(expected["ndmps"]["roll_option"])
    for got, want in zip(fig.ndmps["roll_option"], expected["ndmps"]["roll_option"]):
        assert got == approx(want)
    assert fig.info.end.direction == Direction.DOWNWIND


def test_spin_and_quarter_rolls_every_option_exits_reversed(mb: ManBuilder):
    fig = parse_olan("-5isiBb(1.)8", mb)[0]
    itrans = g.Transformation(
        g.Euler(fig.olan.entry, 0, Heading.RTOL), g.P0()
    )
    exits = [_exit_bearing(fig, i, itrans) for i in range(2)]

    assert exits == approx([0, 0], abs=1e-6)
    # info agrees with the geometry
    assert fig.aresti.info.end.direction == Direction.parse_heading(
        Heading.infer(fig.template.att.bearing()[-1]), Heading.LTOR
    )


def test_cross_box_exit_with_single_roll_emits_no_roll_option(mb: ManBuilder):
    fig = parse_olan(CASE_2, mb)[0]

    assert fig.aresti.info.end.direction == Direction.CROSS
    assert fig.aresti.ndmps == {}
    assert "roll_option" not in fig.definition.mps.data


def test_cross_box_entry_links_spin_and_roll(mb: ManBuilder):
    figs = parse_olan(CASE_2, mb)
    fig = figs[1]

    assert fig.aresti.info.start.direction == Direction.CROSS
    spin, roll = fig.aresti.elements[:2]
    assert spin.kind == "spin" and spin.args == ["roll_option[0]"]
    assert roll.kind == "roll" and roll.args == [["roll_option[1]"]]
    assert len(fig.aresti.ndmps["roll_option"]) == 2
    option = fig.definition.mps.data["roll_option"]
    assert len(option.collectors) == 2

    entry = g.Transformation(
        g.Euler(fig.olan.entry, 0, Heading.OUTTOIN), g.P0()
    )
    exits = np.array([_exit_bearing(fig, i, entry) for i in range(2)])
    assert abs(np.cos(exits[0] - exits[1]) + 1) < 1e-9  # differ by 180 degrees


def test_direction_lines_use_net_roll_wrapping_to_quarter(mb: ManBuilder):
    def lines(code):
        return OlanFig.take([code])[0].direction_lines()

    for code in ("b4", "b3", "b5", "b,4", "b8", "4b4"):
        assert lines(code), code
    for code in ("b24", "b84", "b1", "b2", "b22", "b"):
        assert not lines(code), code


def test_definition_info_matches_final_aresti_info(mb: ManBuilder):
    figs = parse_olan(
        "3% /+`,2ifpbb(````````,34...)'22`-~~ (-2,-1) 4% ``-````,5is,2ib````,24'-```",
        mb,
    )
    for fig in figs:
        for key in ("position", "start", "end"):
            assert getattr(fig.definition.info, key) == getattr(fig.aresti.info, key)
    assert figs[1].definition.info.start.direction == Direction.CROSS
    assert figs[1].definition.info.end.direction != Direction.CROSS


# D2: a sequence we receive links up; one that does not raises


def test_a_figure_that_does_not_link_raises(mb: ManBuilder):
    with pytest.raises(OlanParseError) as info:
        parse_olan("m1- 4h4", mb)
    e = info.value
    assert (e.token, e.index, e.figure) == ("4h4", 1, 2)
    assert e.message == (
        'Figure 2 "4h4": starts upright, but figure 1 "m1-" ends inverted. Each figure '
        "must start in the attitude the figure before it ends in. An OpenAero free known "
        "file lists only the compulsory figures, so it cannot be read as a sequence."
    )


def test_an_inverted_start_after_an_upright_exit_raises(mb: ManBuilder):
    with pytest.raises(OlanParseError, match='Figure 3 "-o": starts inverted, but figure 2 "o" ends upright'):
        parse_olan("eu o o -o", mb)


@pytest.mark.parametrize(
    "olan",
    ["m1- -4h4", "-4h4 m", "-ic", "m1- eu 4h4", "m1- ed 4h4", "m1- ej 4h4", "m1- eja 4h4", "m1- // 4h4"],
)
def test_figures_that_link_or_restart_parse(mb: ManBuilder, olan: str):
    """Linked figures, a first figure written inverted, and a join after a
    subsequence or an entry command (which restart the attitude, as in OpenAero)."""
    assert len(parse_olan(olan, mb)) == len([t for t in olan.split() if t not in ("eu", "ed", "ej", "eja", "//")])
