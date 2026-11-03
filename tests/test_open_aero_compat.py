import pytest

from pyolan.drawing import re_drawing
from pyolan.figure_parser import OlanFig
from pyolan.primitives import olan_figs
from pyolan.rolls import OlanRoll, sn, spi
from schemas.positioning import Orientation


@pytest.mark.parametrize("figure_code", sorted(olan_figs))
def test_open_aero_figure_codes_parse_and_build(figure_code):
    """Every figure code registered by OpenAero's primitive catalogue is usable."""
    figure = OlanFig.take([figure_code])[0]

    assert figure_code in figure.fig.chars.split("|")
    assert figure.create_elements()


@pytest.mark.parametrize(
    ("figure_code", "element_kinds"),
    [
        ("d", ["Loop", "Line", "Loop"]),
        ("v", ["Loop", "Line", "Loop"]),
        ("a", ["Line", "Loop", "Line"]),
        ("o", ["Loop"]),
        ("ao", ["Line", "Loop", "Loop", "Line"]),
        ("q", ["Line", "Loop", "Line", "Loop"]),
        ("c", ["Line", "Loop", "Line", "Loop"]),
        ("g", ["Loop", "Line", "Loop", "Line", "Loop"]),
        ("h", ["Loop", "Line", "Stallturn", "Line", "Loop"]),
        ("ta", ["Loop", "Line", "Tailslide", "Line", "Loop"]),
        ("n", ["Loop", "Line", "Loop", "Line", "Loop", "Line", "Loop"]),
        ("w", ["Loop", "Line", "Loop", "Line", "Loop", "Line", "Loop"]),
        ("j", ["Turn"]),
        ("jo", ["Turn"]),
    ],
)
def test_open_aero_primitive_element_shapes(figure_code, element_kinds):
    figure = OlanFig.take([figure_code])[0]

    assert [element.kind for element in figure.fig.oels] == element_kinds


@pytest.mark.parametrize(
    ("roll_code", "turns"),
    [
        ("1", [1]),
        ("2", [0.5]),
        ("22", [0.5, 0.5]),
        ("32", [0.5, 0.5, 0.5]),
        ("42", [0.5, 0.5, 0.5, 0.5]),
        ("3", [0.75]),
        ("4", [0.25]),
        ("24", [0.25, 0.25]),
        ("34", [0.25, 0.25, 0.25]),
        ("44", [0.25, 0.25, 0.25, 0.25]),
        ("54", [0.25] * 5),
        ("64", [0.25] * 6),
        ("74", [0.25] * 7),
        ("84", [0.25] * 8),
        ("5", [1.25]),
        ("6", [1.5]),
        ("7", [1.75]),
        ("8", [0.125, 0.125]),
        ("48", [0.125] * 4),
        ("68", [0.125] * 6),
        ("88", [0.125] * 8),
        ("9", [2]),
    ],
)
def test_open_aero_roll_amounts(roll_code, turns):
    assert OlanRoll.parse(roll_code).turns() == turns


def test_open_aero_roll_separators_and_special_rolls():
    assert OlanRoll.parse("1f,1f").roll_arr == [sn(1, False), sn(-1, False)]
    assert OlanRoll.parse("1s;1is").roll_arr == [
        spi(1, False),
        spi(1, True),
    ]
    assert OlanRoll.parse("2,2").turns() == [0.5, -0.5]
    assert OlanRoll.parse("2;2").turns() == [0.5, 0.5]
    assert OlanRoll.parse("f").roll_arr == [sn(1, False)]
    assert OlanRoll.parse("is").roll_arr == [spi(1, True)]


@pytest.mark.parametrize(
    "drawing",
    [
        "ed",
        "ej",
        "eja",
        "eu",
        "//",
        "[1,2]",
        "(-1,2)",
        "100%",
        ">",
        "11>",
        "^",
        "/",
        "~",
        "+",
        '"sequence comment"',
        "@A",
    ],
)
def test_open_aero_drawing_tokens_are_not_figures(drawing):
    assert re_drawing.match(drawing)
    with pytest.raises(Exception, match="No olan figure"):
        OlanFig.take([drawing])


@pytest.mark.parametrize(
    ("figure_code", "prefix", "suffix", "entry_inverted", "exit_inverted"),
    [
        ("-o-", "", "", True, True),
        ("o", "", "", False, False),
        ("-ry", "", "", True, False),
        ("ry-", "", "", False, True),
        ("o8;5f-", "", "8;5f", False, True),
    ],
)
def test_open_aero_attitude_and_roll_forms(
    figure_code, prefix, suffix, entry_inverted, exit_inverted
):
    figure = OlanFig.take([figure_code])[0]

    assert figure.entry == (
        Orientation.INVERTED if entry_inverted else Orientation.UPRIGHT
    )
    assert figure.exit == (
        Orientation.INVERTED if exit_inverted else Orientation.UPRIGHT
    )
    if prefix:
        assert figure.prefix == OlanRoll.parse(prefix)
    if suffix:
        assert figure.final.turns() == OlanRoll.parse(suffix).turns()
