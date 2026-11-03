import json
from pathlib import Path

import pytest
from schemas.positioning import Orientation

from pyolan.figure_parser import OlanFig


FIXTURE = json.loads(
    (Path(__file__).parent / "data" / "openaero" / "figures.json").read_text()
)
FIGURES = FIXTURE["figures"]
BY_CODE = {}
for figure in FIGURES:
    if figure["base_code"]:
        BY_CODE.setdefault(figure["base_code"], figure)

RENDERER_ONLY_PATTERNS = {
    "+$ihat(_)&+", "+$ivv(_)&+", "+^itri(^)^-", "+^itri(^)_+",
    "+^itri(_)^+", "+^itri(_)_-", "+^ixm(_)_+", "+_itri(^)^+",
    "+_itri(^)_-", "+_itri(_)^-", "+_itri(_)_+", "+_ixm(^)_+",
    "+_ixm(_)^+", "+_ixm(_)_+", "+idvd+", "+idvz-", "+idz-",
    "+irqq-", "-$ihat(_)&-", "-$ivv(_)&-", "-^itri(^)^+",
    "-^itri(^)_-", "-^itri(_)^-", "-^itri(_)_+", "-^ixm(_)_-",
    "-_itri(^)^-", "-_itri(^)_+", "-_itri(_)^+", "-_itri(_)_-",
    "-_ixm(^)_-", "-_ixm(_)^-", "-_ixm(_)_-", "-idvd-", "-idvz+",
    "-idz+", "-irqq+",
}


def parseable_figures():
    seen = set()
    for figure in FIGURES:
        if not figure["base_code"] or figure["pattern"] in seen:
            continue
        seen.add(figure["pattern"])
        try:
            parsed = OlanFig.take([figure["pattern"]])[0]
        except Exception:
            continue
        yield figure, parsed


def pyolan_semantic(code):
    figure = OlanFig.take([code])[0]
    return [
        {
            "kind": element.kind,
            "amount": element.loopamount,
            "can_roll": element.canRoll,
            "direction": element.direction,
            "rolltype": element.rolltype,
            "turnamount": element.turnamount,
        }
        for element in figure.fig.oels
    ]


def test_fixture_has_open_aero_provenance():
    source = FIXTURE["source"]

    assert source["repository"] == "PyFlightCoach/OpenAero"
    assert len(source["revision"]) == 40
    assert source["file"] == "data/figures/figures.js"
    assert FIGURES


def test_renderer_only_open_aero_patterns_are_explicitly_out_of_scope():
    """These inverted renderer variants are not OLAN parser inputs."""
    unsupported = set()
    seen = set()
    for figure in FIGURES:
        pattern = figure["pattern"]
        if not figure["base_code"] or pattern in seen:
            continue
        seen.add(pattern)
        try:
            OlanFig.take([pattern])
        except Exception:
            unsupported.add(pattern)

    assert unsupported == RENDERER_ONLY_PATTERNS
    assert len(unsupported) == 36


def test_fixture_contains_k_factors_for_all_definitions():
    assert len(FIGURES) > 1000
    assert all(
        isinstance(figure["k_powered"], (int, float))
        and isinstance(figure["k_glider"], (int, float))
        for figure in FIGURES
    )


def test_fixture_contains_normalized_open_aero_semantics():
    assert all(
        set(figure["semantics"])
        == {
            "attitude",
            "roll_slots",
            "roll_markers",
            "drawing_operations",
            "drawing_shapes",
            "render_plan",
        }
        for figure in FIGURES
    )


@pytest.mark.parametrize(
    ("pattern", "entry", "exit", "roll_slots"),
    [
        ("+d_-", "upright", "inverted", []),
        ("-d_-", "inverted", "inverted", []),
        ("+_ao(_)_-", "upright", "inverted", ["_"]),
        ("-^tri(^)^+", "inverted", "upright", ["^"]),
    ],
)
def test_open_aero_pattern_semantics(pattern, entry, exit, roll_slots):
    figure = next(item for item in FIGURES if item["pattern"] == pattern)

    assert figure["semantics"]["attitude"] == {"entry": entry, "exit": exit}
    assert figure["semantics"]["roll_slots"] == roll_slots


@pytest.mark.parametrize(
    ("pattern", "roll_markers", "drawing_shapes"),
    [
        ("+d_-", ["_"], ["d", "z"]),
        ("+v&+", ["&"], ["v", "V"]),
        ("+o_+", ["_"], ["o"]),
        ("+&ry_+", ["&", "_"], ["v", "c", "d"]),
        ("+&n(_)&+", ["&", "_", "&"], ["v", "z", "Z", "V"]),
        ("+_cm(_)_+", ["_", "_", "_"], ["c", "C"]),
        ("+_tri(_)_+", ["_", "_", "_"], ["d", "z", "z", "d"]),
        ("+_xm(_)_+", ["_", "_", "_"], ["d", "d", "d", "d"]),
    ],
)
def test_open_aero_structural_tokens(
    pattern, roll_markers, drawing_shapes
):
    figure = next(item for item in FIGURES if item["pattern"] == pattern)

    assert figure["semantics"]["roll_markers"] == roll_markers
    assert figure["semantics"]["drawing_shapes"] == drawing_shapes


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (
            "+d_-",
            [
                {"kind": "line", "length": 1},
                {"kind": "arc", "shape": "d", "angle": 45},
                {"kind": "line", "length": 1},
                {"kind": "roll", "marker": "_"},
                {"kind": "line", "length": 1},
                {"kind": "arc", "shape": "z", "angle": 135},
                {"kind": "line", "length": 1},
            ],
        ),
        (
            "+_xm(_)_+",
            [
                {"kind": "line", "length": 1},
                {"kind": "arc", "shape": "d", "angle": 45},
                {"kind": "roll", "marker": "_"},
                {"kind": "arc", "shape": "d", "angle": 45},
                {"kind": "roll", "marker": "_"},
                {"kind": "arc", "shape": "d", "angle": 45},
                {"kind": "roll", "marker": "_"},
                {"kind": "arc", "shape": "d", "angle": 45},
                {"kind": "line", "length": 1},
            ],
        ),
    ],
)
def test_open_aero_render_plan(pattern, expected):
    figure = next(item for item in FIGURES if item["pattern"] == pattern)

    assert figure["semantics"]["render_plan"] == expected


def test_render_plans_are_well_formed():
    for figure in FIGURES:
        for item in figure["semantics"]["render_plan"]:
            assert item["kind"] in {
                "line",
                "arc",
                "roll",
                "embedded_roll",
                "special",
                "turn",
            }
            if item["kind"] == "line":
                assert item["length"] > 0
            elif item["kind"] == "arc":
                assert item["angle"] in {
                    -360, -315, -270, -225, -180, -135, -90, -45,
                    45, 90, 135, 180, 225, 270, 315, 360,
                }


@pytest.mark.parametrize("figure", FIGURES[:200])
def test_open_aero_pattern_semantics_are_well_formed(figure):
    semantics = figure["semantics"]

    assert semantics["attitude"]["entry"] in {"upright", "inverted"}
    assert semantics["attitude"]["exit"] in {"upright", "inverted"}
    assert all(isinstance(slot, str) for slot in semantics["roll_slots"])
    assert all(
        operation in "~+/^'`._" for operation in semantics["drawing_operations"]
    )


@pytest.mark.parametrize(
    "pattern",
    ["+d_-", "-d_-", "+_ao(_)_-", "-^tri(^)^+"],
)
def test_pyolan_preserves_open_aero_pattern_attitude(pattern):
    source = next(item for item in FIGURES if item["pattern"] == pattern)
    parsed = OlanFig.take([pattern])[0]

    assert parsed.fig.chars == source["base_code"]
    assert parsed.entry == (
        Orientation.INVERTED
        if source["semantics"]["attitude"]["entry"] == "inverted"
        else Orientation.UPRIGHT
    )
    assert parsed.exit == (
        Orientation.INVERTED
        if source["semantics"]["attitude"]["exit"] == "inverted"
        else Orientation.UPRIGHT
    )


def test_all_parseable_open_aero_attitudes_match_pyolan():
    checked = 0

    for source, parsed in parseable_figures():
        assert parsed.entry == (
            Orientation.INVERTED
            if source["semantics"]["attitude"]["entry"] == "inverted"
            else Orientation.UPRIGHT
        )
        assert parsed.exit == (
            Orientation.INVERTED
            if source["semantics"]["attitude"]["exit"] == "inverted"
            else Orientation.UPRIGHT
        )
        checked += 1

    assert checked >= 1100


@pytest.mark.parametrize("code", ["dq", "qo", "qq", "rqq"])
def test_signed_arc_sequence_matches_open_aero(code):
    source = BY_CODE[code]
    parsed = OlanFig.take([code])[0]
    open_aero_arcs = [
        item["angle"] / 360
        for item in source["semantics"]["render_plan"]
        if item["kind"] == "arc"
    ]
    pyolan_arcs = [
        element.loopamount
        for element in parsed.fig.oels
        if element.kind == "Loop"
    ]

    assert pyolan_arcs == open_aero_arcs


@pytest.mark.parametrize(
    ("code", "aresti", "k_powered", "k_glider"),
    [
        ("d", "1.1.2.2", 8, 8),
        ("v", "1.1.6.1", 10, 10),
        ("o", "7.4.1.1", 10, 10),
        ("ry", "8.5.17.1", 12, 12),
        ("n", "1.3.9.1", 24, 0),
        ("cm", "7.5.1.1", 16, 16),
        ("tri", "0.11.1", 20, 20),
        ("xm", "0.101.1", 20, 20),
    ],
)
def test_representative_open_aero_metadata(code, aresti, k_powered, k_glider):
    figure = BY_CODE[code]

    assert figure["aresti"] == aresti
    assert figure["k_powered"] == k_powered
    assert figure["k_glider"] == k_glider


@pytest.mark.parametrize("code", ["d", "v", "o", "ry", "n", "cm", "tri", "xm"])
def test_representative_generated_codes_parse_in_pyolan(code):
    figure = OlanFig.take([code])[0]

    assert figure.fig.chars == code
    assert figure.create_elements()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (
            "d",
            [
                ("Loop", 1 / 8, False),
                ("Line", 0, True),
                ("Loop", -1 / 8, False),
            ],
        ),
        (
            "v",
            [
                ("Loop", 1 / 4, False),
                ("Line", 0, True),
                ("Loop", -1 / 4, False),
            ],
        ),
        ("o", [("Loop", 1, True)]),
        (
            "ry",
            [
                ("Loop", 1 / 4, False),
                ("Line", 0, True),
                ("Loop", 5 / 8, False),
                ("Line", 0, True),
                ("Loop", 1 / 8, False),
            ],
        ),
        (
            "n",
            [
                ("Loop", 1 / 4, False),
                ("Line", 0, True),
                ("Loop", 3 / 8, False),
                ("Line", 0, True),
                ("Loop", -3 / 8, False),
                ("Line", 0, True),
                ("Loop", -1 / 4, False),
            ],
        ),
        (
            "cm",
            [
                ("Line", 0, True),
                ("Loop", 5 / 8, False),
                ("Line", 0, True),
                ("Loop", -5 / 8, False),
                ("Line", 0, True),
            ],
        ),
        (
            "tri",
            [
                ("Loop", 1 / 8, False),
                ("Line", 0, True),
                ("Loop", 3 / 8, False),
                ("Line", 0, True),
                ("Loop", -3 / 8, False),
                ("Line", 0, True),
                ("Loop", -1 / 8, False),
            ],
        ),
        (
            "xm",
            [
                ("Loop", 1 / 8, True),
                ("Loop", 1 / 8, True),
                ("Loop", 1 / 8, True),
                ("Loop", 1 / 8, False),
            ],
        ),
    ],
)
def test_representative_open_aero_semantics(code, expected):
    actual = [
        (element["kind"], element["amount"], element["can_roll"])
        for element in pyolan_semantic(code)
    ]

    assert actual == expected


def test_generated_fixture_has_one_normalized_record_per_definition_code():
    assert set(BY_CODE) >= {"d", "v", "o", "ry", "n", "cm", "tri", "xm"}


@pytest.mark.parametrize("code", ["d", "v", "o", "ry", "n", "cm", "tri", "xm"])
def test_pyolan_element_count_matches_open_aero_render_arcs(code):
    source = BY_CODE[code]
    arcs = [
        item
        for item in source["semantics"]["render_plan"]
        if item["kind"] == "arc"
    ]
    parsed = OlanFig.take([code])[0]

    assert len([element for element in parsed.fig.oels if element.kind == "Loop"]) == len(
        arcs
    )


def test_extended_immelman_preserves_open_aero_roll_slots():
    parsed = OlanFig.take(["1xm(1)1"])[0]

    assert [element.canRoll for element in parsed.fig.oels] == [
        True,
        True,
        True,
        False,
    ]


def test_reverse_cuban_matches_open_aero_arc_and_roll_structure():
    source = BY_CODE["rcc"]
    parsed = OlanFig.take(["rcc"])[0]
    plan = source["semantics"]["render_plan"]

    assert len([item for item in plan if item["kind"] == "arc"]) == 3
    assert len([item for item in plan if item["kind"] == "roll"]) == 3
    assert len([element for element in parsed.fig.oels if element.kind == "Loop"]) == 3
    assert len([element for element in parsed.fig.oels if element.canRoll]) == 3


@pytest.mark.parametrize(
    "code",
    [
        "tri",
        "rcc",
        "vv",
        "hat",
        "xm",
        "xa",
        "co",
        "hp",
        "dq",
        "qo",
        "qq",
        "rqq",
    ]
)
def test_roll_slot_count_matches_open_aero_definition(code):
    source = BY_CODE[code]
    parsed = OlanFig.take([code])[0]
    open_aero_slots = sum(
        marker in "_^&$" for marker in source["semantics"]["roll_markers"]
    )

    assert sum(element.canRoll for element in parsed.fig.oels) == open_aero_slots


@pytest.mark.parametrize(
    ("code", "special_shape", "element_kind"),
    [
        ("h", "h", "Stallturn"),
        ("ta", "t", "Tailslide"),
    ],
)
def test_special_figures_match_open_aero_structure(code, special_shape, element_kind):
    source = BY_CODE[code]
    parsed = OlanFig.take([code])[0]
    plan = source["semantics"]["render_plan"]

    assert [item["shape"] for item in plan if item["kind"] == "special"] == [
        special_shape
    ]
    assert [element.kind for element in parsed.fig.oels].count(element_kind) == 1


@pytest.mark.parametrize("code", ["h", "dh", "dhd", "hd", "hp", "th", "ta"])
def test_hammer_and_tailslide_plans_have_explicit_special_shapes(code):
    source = BY_CODE[code]

    assert any(item["kind"] == "special" for item in source["semantics"]["render_plan"])


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (
            "jj",
            [
                ("Turn", 0, True, "i", 1 / 4),
                ("Turn", 0, True, "i", 1 / 4),
            ],
        ),
        ("jo", [("Turn", 0, True, "o", 1 / 4)]),
        (
            "jijo",
            [
                ("Turn", 0, True, "i", 1 / 4),
                ("Turn", 0, True, "o", 1 / 4),
            ],
        ),
        (
            "jjoi",
            [
                ("Turn", 0, True, "i", 1 / 4),
                ("Turn", 0, True, "oi", 1 / 2),
            ],
        ),
        (
            "jojio",
            [
                ("Turn", 0, True, "o", 1 / 4),
                ("Turn", 0, True, "io", 1 / 2),
            ],
        ),
    ],
)
def test_open_aero_turn_family_semantics(code, expected):
    actual = [
        (
            element["kind"],
            element["amount"],
            element["can_roll"],
            element["rolltype"],
            element["turnamount"],
        )
        for element in pyolan_semantic(code)
    ]

    assert actual == expected


@pytest.mark.parametrize(
    ("code", "turnamount"),
    [("oaj", 1 / 4), ("oajj", 1 / 2), ("oajjj", 3 / 4), ("oajjjj", 1)],
)
def test_open_aero_loop_and_turn_variants(code, turnamount):
    source = BY_CODE[code]
    parsed = OlanFig.take([code])[0]

    assert source["semantics"]["render_plan"][-2]["kind"] == "turn"
    assert source["semantics"]["render_plan"][-2]["token"] == f"j{int(turnamount * 4)}"
    assert parsed.fig.oels[-1].kind == "Turn"
    assert parsed.fig.oels[-1].turnamount == turnamount


@pytest.mark.parametrize(
    ("code", "turnamount", "roll_total", "rolltype"),
    [
        ("j", 1 / 4, 0, "i"),
        ("1j5", 1 / 4, 5, "i"),
        ("2jio15", 1 / 2, 1.5, "io"),
        ("3j3", 3 / 4, 3, "i"),
        ("4j5", 1, 5, "i"),
        ("4jio3", 1, 1, "io"),
        ("4joi4", 1, 0, "oi"),
    ],
)
def test_open_aero_rolling_turn_tokens_match_pyolan(
    code, turnamount, roll_total, rolltype
):
    source = BY_CODE[code]
    parsed = OlanFig.take([code])[0]
    turns = [element for element in parsed.fig.oels if element.kind == "Turn"]
    tokens = [
        item["token"]
        for item in source["semantics"]["render_plan"]
        if item["kind"] == "turn"
    ]

    assert len(tokens) == len(turns) == 1
    assert tokens[0].lower().startswith("j")
    assert turns[0].turnamount == turnamount
    assert turns[0].rolltype == rolltype
    assert sum(
        sum(roll.turns()) for roll in parsed.element_rolls() if roll
    ) == roll_total


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (
            "dz",
            [
                ("Loop", 1 / 8, False),
                ("Line", 0, True),
                ("Loop", -1 / 8, False),
                ("Loop", 3 / 8, False),
                ("Line", 0, True),
                ("Loop", -3 / 8, False),
            ],
        ),
        (
            "dvz",
            [
                ("Loop", 1 / 4, False),
                ("Line", 0, True),
                ("Loop", -1 / 4, False),
                ("Loop", 1 / 4, False),
                ("Line", 0, True),
                ("Loop", -1 / 4, False),
                ("Loop", 1 / 4, False),
                ("Line", 0, True),
                ("Loop", -1 / 4, False),
            ],
        ),
        (
            "dvd",
            [
                ("Loop", 1 / 4, False),
                ("Line", 0, True),
                ("Loop", -1 / 4, False),
                ("Loop", -1 / 4, False),
                ("Line", 0, True),
                ("Loop", 1 / 4, False),
                ("Loop", -1 / 4, False),
                ("Line", 0, True),
                ("Loop", 1 / 4, False),
            ],
        ),
        ("vv", [("Loop", 1 / 4, False), ("Line", 0, True), ("Loop", -1 / 4, False), ("Line", 0, True), ("Loop", 1 / 4, False), ("Line", 0, True), ("Loop", -1 / 4, False)]),
        ("hat", [("Loop", 1 / 4, False), ("Line", 0, True), ("Loop", -1 / 4, False), ("Line", 0, True), ("Loop", 1 / 4, False), ("Line", 0, True), ("Loop", -1 / 4, False)]),
    ],
)
def test_open_aero_extended_loop_family_semantics(code, expected):
    actual = [
        (element["kind"], element["amount"], element["can_roll"])
        for element in pyolan_semantic(code)
    ]

    assert actual == expected
