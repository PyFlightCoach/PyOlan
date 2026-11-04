from pathlib import Path

import numpy as np
from flightanalysis.builders.manbuilder import ManBuilder
from flightdata import State
from pytest import approx, fixture
from schemas.positioning import Direction, Heading
from tuning.builders import load_builder

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

    assert fig.aresti.elements[0].kind == "roll"
    assert fig.aresti.elements[1].kind == "loop"
    assert fig.aresti.elements[1].kwargs["ke"] == approx(np.radians(30))
    assert fig.aresti.elements[0].args == [approx(np.radians(60))]
    assert fig.aresti.elements[2].args == [approx(np.radians(-60))]
    assert fig.aresti.info.k == 6

    assert fig.definition.eds[2].props["ke"] == approx(np.radians(30))


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


def test_parse_olan_generates_roll_options_in_ndmps(mb: ManBuilder):
    fig = parse_olan("d1", mb)[0]

    assert fig.aresti.ndmps == {"roll_option": [[2 * np.pi]]}


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
    olanstr = Path("tests/test_data/iac_unl_2026").read_text()
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