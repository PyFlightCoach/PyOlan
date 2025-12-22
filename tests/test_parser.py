import numpy as np
from pytest import approx, fixture
from schemas.positioning import Direction, Heading
from tuning.builders import load_builder
from flightanalysis.builders.manbuilder import ManBuilder
from pyolan.parser import ParsedOlanFig, parse_olan
from flightdata import State

@fixture(scope="session")
def mb() -> ManBuilder:
    return load_builder("IAC", category="unlimited")

def test_entry_direction(mb: ManBuilder):
    ofigs = parse_olan("13% -``5if```,4ao(,1),22+`", mb)
    assert ofigs[0].aresti.info.start.direction == Direction.UPWIND


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

    assert fig.definition.eds[2].props["ke"] == approx(np.radians(30))


def test_tailslide(mb: ManBuilder):
    fig: ParsedOlanFig = parse_olan("~~.,3ita'3....~>", mb)


def test_iac_unl_2026_n(mb: ManBuilder):
    fig: ParsedOlanFig = parse_olan("7% ``-if....'in(.,3,34...'').....''-~~", mb)[0]
    


    pass


def test_iac_adv_2026(mb: ManBuilder):
    figs = parse_olan("44c,2 (2,0) 9% m1- (12,0) /~~---.h.....''2f.......+++~~ (-16,0) ~++..''n(.'24...).24.'- (-2,0) -5is...''iBb()......'8' 3% 6m~~ (11,0) 22% ,6fic2- -a3',34+ 6% +8pb3..''+``` 3% 2> `44'm24+~~ (5,0) 4% 3jo3", mb)
    assert len(figs) == 11
    names = [f.aresti.info.short_name for f in figs]
    assert len(set(names)) == len(names)  # all names unique
    pass