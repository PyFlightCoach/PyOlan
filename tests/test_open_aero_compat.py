import pytest

from pyolan.drawing import re_drawing
from pyolan.figure_parser import OlanFig
from pyolan.primitives import olan_figs
from pyolan.rolls import OlanRoll, sn, spi


# a rolling turn needs its rolls: "jo" alone is not an OpenAero figure (F19)
WRITTEN = {"jo": "1jo1", "jio": "2jio2", "joi": "2joi2"}


@pytest.mark.parametrize("figure_code", sorted(olan_figs))
def test_open_aero_figure_codes_parse_and_build(figure_code):
    """Every figure code registered by OpenAero's primitive catalogue is usable."""
    figure = OlanFig.take([WRITTEN.get(figure_code, figure_code)])[0]

    assert figure_code in figure.fig.chars.split("|")
    assert figure.create_elements()


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


def test_open_aero_roll_prefix_and_suffix_forms():
    figure = OlanFig.take(["o8;5f-"])[0]

    assert figure.final.turns() == OlanRoll.parse("8;5f").turns()
