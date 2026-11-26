import json
import re
from pathlib import Path

import pytest

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

    sha = (Path(__file__).parents[1] / "tools/openaero/OPENAERO_SHA").read_text().strip()
    assert source["repository"] == "OpenAero/main"
    assert source["revision"] == sha
    assert source["dirty"] is False
    assert source["harness_version"]
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


def test_fixture_parseability_boundary_is_stable():
    assert sum(1 for _ in parseable_figures()) == 1127


def test_fixture_contains_k_factors_for_all_definitions():
    assert len(FIGURES) > 1000
    assert all(
        isinstance(figure["k_powered"], (int, float))
        and isinstance(figure["k_glider"], (int, float))
        for figure in FIGURES
    )


def test_fixture_metadata_and_patterns_are_well_formed():
    patterns = [figure["pattern"] for figure in FIGURES]

    assert len(patterns) == len(set(patterns))
    for figure in FIGURES:
        assert re.fullmatch(r"\d+(?:\.\d+){1,3}", figure["aresti"])
        assert isinstance(figure["k_powered"], int)
        assert isinstance(figure["k_glider"], int)
        assert figure["k_powered"] >= 0
        assert figure["k_glider"] >= 0


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


def test_generated_fixture_has_one_normalized_record_per_definition_code():
    assert set(BY_CODE) >= {"d", "v", "o", "ry", "n", "cm", "tri", "xm"}


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
        # an outside rolling turn needs a roll ("jo" alone is not an OpenAero figure)
        ("1jo1", [("Turn", 0, True, "o", 1 / 4)]),
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
    ("code", "olan", "turnamount", "rolltype"),
    [
        # rolls that end inverted are written with "-" after them (F19)
        ("j", "j", 1 / 4, "i"),
        ("1j5", "1j5-", 1 / 4, "i"),
        ("2jio15", "2jio15-", 1 / 2, "io"),
        ("3j3", "3j3", 3 / 4, "i"),
        ("4j5", "4j5-", 1, "i"),
        ("4jio3", "4jio3", 1, "io"),
        ("4joi4", "4joi4", 1, "oi"),
    ],
)
def test_open_aero_rolling_turn_tokens_match_pyolan(code, olan, turnamount, rolltype):
    source = BY_CODE[code]
    parsed = OlanFig.take([olan])[0]
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


def test_all_numeric_rolling_turn_definitions_match_open_aero():
    checked = 0
    seen = set()

    for source in FIGURES:
        code = source["base_code"]
        if not code or code in seen:
            continue
        match = re.fullmatch(r"([1-4])j(io|oi|i|o)?(\d*)", code)
        if not match:
            continue
        seen.add(code)

        parsed = OlanFig.take([source["pattern"]])[0]
        turns = [element for element in parsed.fig.oels if element.kind == "Turn"]
        tokens = [
            item["token"]
            for item in source["semantics"]["render_plan"]
            if item["kind"] == "turn"
        ]
        expected_rolltype = match.group(2) or "i"

        assert len(turns) == len(tokens) == 1
        assert turns[0].turnamount == int(match.group(1)) / 4
        assert turns[0].rolltype == expected_rolltype
        assert tokens[0].lower().startswith("j")
        checked += 1

    assert checked >= 40


def test_turn_render_tokens_match_parseable_turn_elements():
    checked = 0
    seen = set()

    for source in FIGURES:
        pattern = source["pattern"]
        if not source["base_code"] or pattern in seen:
            continue
        seen.add(pattern)

        tokens = [
            item["token"]
            for item in source["semantics"]["render_plan"]
            if item["kind"] == "turn"
        ]
        if not tokens:
            continue

        parsed = OlanFig.take([pattern])[0]
        turns = [element for element in parsed.fig.oels if element.kind == "Turn"]
        if len(tokens) != len(turns):
            continue

        for token, turn in zip(tokens, turns):
            letters = token[1:]
            digits = ""
            rolltype = ""
            while letters and not letters[0].isdigit():
                rolltype += letters[0]
                letters = letters[1:]
            digits = letters
            rolltype = rolltype.lower()
            if rolltype:
                assert sorted(turn.rolltype) == sorted(rolltype)
            assert turn.turnamount == int(digits[0]) / 4
        checked += 1

    assert checked >= 90


