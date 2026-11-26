"""The loops and lines of an OLAN figure that the rules compare (Phase S, S1).

docs/plans/olan-figure-sizing.md in FCScoreFuture holds the rulebook tables these
expectations come from, and the decisions SQ1-SQ7 (2026-11-26).
"""

import json
from collections import defaultdict
from pathlib import Path

import geometry as g
import pytest
import schemas.positioning as p
from flightanalysis.manoeuvre import Manoeuvre
from flightdata import State
from tuning.builders import load_builder, sizing_info

from pyolan.drawn import elements_from_draw
from pyolan.figure_parser import OlanFig
from pyolan.parser import parse_olan
from pyolan.sizing import Sizing, in_families

RULES = ("IAC", "IACGlider", "CIVA", "CIVAGlider", "IMAC")
FIGURES = json.loads(
    (Path(__file__).parent / "data" / "openaero" / "figures.json").read_text()
)["figures"]


@pytest.fixture(scope="module")
def policies():
    return {r: Sizing.parse(sizing_info(r)) for r in RULES}


def test_round_and_corner_loops():
    """OpenAero's makeCorner: under 180 degrees and not followed by "=" is a corner."""
    oels, _ = elements_from_draw("~d~v~d~")  # 3.3.1
    assert [e.round for e in oels if e.kind == "Loop"] == [False] * 3
    oels, _ = elements_from_draw("~_v=m!_V=_~")  # 7.4.7: a 3/4 loop, then a 1/4 loop
    assert [e.round for e in oels if e.kind == "Loop"] == [True, True]
    oels, _ = elements_from_draw("~~~~v~_~m!_V=_~")  # 8.6.9: the first 1/4 is a corner
    assert [e.round for e in oels if e.kind == "Loop"] == [False, True, True]


def test_families_are_aresti_prefixes():
    assert in_families("7.4.3.1", ["7.4.3"])
    assert not in_families("7.4.13.1", ["7.4.1"])
    assert in_families("3.8.1.2", ["3"])


def test_unknown_sizing_keys_are_refused():
    with pytest.raises(ValueError):
        Sizing.parse({"radii": "round"})


def test_f3a_has_no_sizing():
    assert sizing_info("f3a") is None


def _all(groups: str) -> tuple[str, ...]:
    return (groups,) * len(RULES)


# The groups by Aresti sub-family for IAC, IAC glider, CIVA, CIVA glider and IMAC.
# Element indices are those of drawn.elements_from_draw; R is loop_radius, R_2 a
# second radius group (loop_radius_2) and L line_length. Rows of Families 3, 7 and 8
# not listed have nothing linked.
_SQUARE = "R:0,2,4,6 L:1,3,5"
_OCTAGON = "R:0,2,4,6,8,10,12,14 L:1,3,5,7,9,11,13"
_DIAMOND = "R:0,2,4,6,8 L:1,3,5,7"
EXPECTED = {
    "3.3.1": _all("R:0,2,4 L:1,3"),
    "3.4.1": _all(_SQUARE),
    "3.4.2": _all(_SQUARE),
    "3.8.1": _all(_OCTAGON),
    # CIVA glider (Figure 29, SQ2): the corners pair with their mirror images
    "7.4.3": (_SQUARE, _SQUARE, _SQUARE, "R:0,6; R_2:2,4 L:1,3,5", _SQUARE),
    "7.4.4": (_SQUARE, _SQUARE, _SQUARE, "R:0,6; R_2:2,4 L:1,3,5", _SQUARE),
    "7.4.5": (_DIAMOND, _DIAMOND, _DIAMOND, "R:0,8; R_2:2,6 L:1,3,5,7", _DIAMOND),
    "7.4.6": (
        _OCTAGON, _OCTAGON, _OCTAGON,
        "R:0,14; R_2:2,12; R_3:4,10; R_4:6,8 L:1,3,5,7,9,11,13",
        _OCTAGON,
    ),
    **{f"7.4.{n}": _all("R:1,2") for n in range(7, 15)},
    **{f"7.5.{n}": _all("R:1,3") for n in range(1, 9)},
    "7.5.9": _all("R:0,1"),
    "7.5.10": _all("R:0,2"),
    # the 45 degree lines of the horizontal 8s: IMAC 8.7.8a, IAC and CIVA by SQ4; the
    # glider rule sets leave them free (IAC 34.20.6.2, CIVA-G B.9.15.2)
    **{f"7.8.{n}": ("R:1,3 L:2,4", "R:1,3") * 2 + ("R:1,3 L:2,4",) for n in range(1, 5)},
    **{f"7.8.{n}": ("R:2,4 L:1,3", "R:2,4") * 2 + ("R:2,4 L:1,3",) for n in range(5, 9)},
    **{f"7.8.{n}": _all("R:2,4") for n in range(9, 17)},
    "7.8.17": _all("R:0,1,2"),
    "7.8.18": _all("R:0,2,3"),
    "7.8.19": _all("R:0,2,3"),
    "7.8.20": _all("R:0,1,2"),
    "7.8.21": _all("R:0,1"),
    "7.8.22": _all("R:0,2"),
    **{f"8.6.{n}": _all("R:2,3") for n in range(9, 13)},
    **{f"8.6.{n}": _all("R:1,2") for n in range(13, 17)},
    "8.10.1": _all("R:1,2"),
    "8.10.2": _all("R:1,2"),
}


def _describe(groups) -> str:
    radii = defaultdict(list)
    for i, name in groups.radius.items():
        radii[name.replace("loop_radius", "R")].append(i)
    out = "; ".join(f"{n}:{','.join(map(str, sorted(v)))}" for n, v in sorted(radii.items()))
    if groups.length:
        out += f" L:{','.join(map(str, sorted(groups.length)))}"
    return out.strip() or "free"


def _catalogue_rows():
    seen = set()
    for f in FIGURES:
        if f["aresti"].split(".")[0] in ("3", "7", "8") and f["pattern"] not in seen:
            seen.add(f["pattern"])
            yield f


def test_every_variant_of_families_3_7_and_8(policies):
    """Every catalogue variant of Families 3, 7 and 8 is drawn from OpenAero's drawing
    string and carries the groups of the tables, under each rule set."""
    wrong = {}
    n = 0
    for f in _catalogue_rows():
        fig = OlanFig.take([f["pattern"]])[0]
        assert fig.drawn_slots is not None, f["pattern"]
        sub = ".".join(f["aresti"].split(".")[:3])
        got = tuple(_describe(fig.size_groups(policies[r])) for r in RULES)
        if got != EXPECTED.get(sub, _all("free")):
            wrong[f["pattern"], sub] = got
        n += 1
    assert not wrong
    assert n > 400


def test_without_a_policy_nothing_is_linked():
    fig = OlanFig.take(["2qo4"])[0]
    assert not fig.size_groups(None)


def _figure(rules: str, olan: str):
    mb = load_builder(rules, category="unlimited")
    return mb, parse_olan(olan, mb, p.Heading.RTOL, sizing_info(rules))[0]


def _collectors(fig, name: str) -> list[str]:
    mps = fig.definition.mps.data
    return [str(c) for c in mps[name].collectors] if name in mps else []


@pytest.mark.parametrize(
    "rules, olan, name, collectors",
    [
        # the roll line of the square loop is one line, its pads collected together
        ("IAC", "2qo4", "line_length", ["e_1.e_1.length.0", "e_3_pad1.e_3_pad2.length.0", "e_5.e_5.length.0"]),
        ("CIVAGlider", "2qo4", "loop_radius", ["e_0.e_0.radius.0", "e_6.e_6.radius.0"]),
        ("CIVAGlider", "2qo4", "loop_radius_2", ["e_2.e_2.radius.0", "e_4.e_4.radius.0"]),
        # a loop with an apex roll is built in parts and collected as one loop; under
        # IMAC its rolling_radius does not replace the linked radius
        ("IAC", "4ao(2)", "loop_radius", ["e_1_pad1.e_1_pad2.radius.0", "e_2.e_2.radius.0"]),
        ("IMAC", "4ao(2)", "loop_radius", ["e_1_pad1.e_1_pad2.radius.0", "e_2.e_2.radius.0"]),
        # glider snap lines (IAC 34.20.4.1; CIVA glider by SQ6)
        ("IACGlider", "qo2f", "line_length", ["e_1.e_1.length.0", "e_5.e_5.length.0"]),
        ("CIVAGlider", "qo2f", "line_length", ["e_1.e_1.length.0", "e_5.e_5.length.0"]),
        ("IAC", "qo2f", "line_length", ["e_1.e_1.length.0", "e_3_pad1.e_3_pad2.length.0", "e_5.e_5.length.0"]),
        ("IAC", "bb", "loop_radius", []),
    ],
)
def test_definitions_collect_the_groups(rules, olan, name, collectors):
    assert _collectors(_figure(rules, olan)[1], name) == collectors


def test_a_second_radius_group_is_like_loop_radius():
    mb, fig = _figure("CIVAGlider", "qq")
    assert set(fig.aresti.ndmps) == {"loop_radius_2", "loop_radius_3", "loop_radius_4"}
    added, template = fig.definition.mps.data["loop_radius_4"], mb.mps.data["loop_radius"]
    assert added.defaul == template.defaul and added.criteria == template.criteria


def test_without_sizing_the_figure_is_built_as_before():
    mb = load_builder("IAC", category="unlimited")
    fig = parse_olan("2qo4", mb, p.Heading.RTOL)[0]
    assert not fig.aresti.ndmps
    assert _collectors(fig, "loop_radius") == [] and _collectors(fig, "line_length") == []


def _inter_downgrades(mb, fig, change=None) -> dict[str, float]:
    """The comparison downgrades of the figure's template, flown with one element changed."""
    data = fig.manoeuvre.to_dict()
    if change is not None:
        uid, attr, factor = change
        (element,) = [e for e in data["elements"] if e["uid"] == uid]
        element[attr] *= factor
    man = Manoeuvre.from_dict(data)
    template = State.stack(man.create_template(g.Transformation(fig.template[0].att, g.P0())), "element")
    results = fig.definition.mps.collect(man, mb.box, template, template)
    return {k: float(sum(v.dgs)) for k, v in results.data.items() if sum(v.dgs) > 1e-3}


@pytest.mark.parametrize(
    "rules, olan, change, downgraded",
    [
        ("IAC", "dvz-", ("e_3", "length", 2), {"line_length"}),  # 3.4.1
        ("IAC", "2qo4", ("e_2", "radius", 1.5), {"loop_radius"}),  # 7.4.3
        # CIVA glider: a top corner is compared with the other top corner only
        ("CIVAGlider", "2qo4", ("e_2", "radius", 1.5), {"loop_radius_2"}),
        ("IAC", "4ao(2)", ("e_2", "radius", 1.5), {"loop_radius"}),  # 7.4.7, apex roll
        ("CIVA", "2ac2", ("e_3", "radius", 1.5), {"loop_radius"}),  # 7.5.1
        ("IMAC", "2cc", ("e_4", "length", 2), {"line_length"}),  # 7.8.1, 45 degree lines
        ("CIVAGlider", "2cc", ("e_4", "length", 2), set()),
        ("IAC", "2cc", ("e_5", "radius", 1.5), set()),  # 7.8.1, the 1/8 is free (SQ1)
        ("IAC", "oo", ("e_1", "radius", 1.5), {"loop_radius"}),  # 7.8.17
        ("IAC", "1rpp2-", ("e_0", "radius", 1.5), set()),  # 8.6.12, the corner is free
        ("IAC", "bb", ("e_2", "radius", 1.5), set()),  # 8.8.1
    ],
)
def test_a_changed_member_is_downgraded(rules, olan, change, downgraded):
    mb, fig = _figure(rules, olan)
    assert _inter_downgrades(mb, fig) == {}
    assert set(_inter_downgrades(mb, fig, change)) == downgraded


def test_the_layout_sizes_a_group_as_one_variable():
    """A linked group is one layout variable, so the layout keeps its members equal."""
    from flightanalysis.layout.variables import collect_variables

    mb, fig = _figure("CIVAGlider", "2qo4")
    keys = {v.key for v in collect_variables(fig.aresti, mb)}
    sizes = {k for k in keys if "radius" in k or "length" in k}
    assert sizes == {"ndmps.loop_radius", "ndmps.loop_radius_2", "ndmps.line_length"}
