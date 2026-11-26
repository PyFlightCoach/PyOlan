import pytest

from pyolan.drawing import re_drawing
from pyolan.errors import OlanParseError
from pyolan.figure_parser import NON_ARESTI, OlanFig
from pyolan.primitives import olan_figs
from pyolan.rolls import OlanRoll, sn, spi


# a rolling turn needs its rolls: "jo" alone is not an OpenAero figure (F19); some
# figures exist in OpenAero only with an attitude marker
WRITTEN = {"jo": "1jo1", "jio": "2jio2", "joi": "2joi2", "dz": "dz-", "dvz": "dvz-", "rqq": "rqq-"}
# PyOlan's own codes that are not OpenAero figures: they raise (D10, plan step 5)
NOT_OPENAERO = {"bh", "ph", "pbh", "jj", "jojo", "jijo", "joji", "joj", "jjoi", "jojio"}
# OpenAero's non-Aresti figures (its Family 0, catalogue numbers 0.x) raise under every
# rule set (Phase S, SQ5), the point tip (D11) among them; they are not parsed and built
NON_ARESTI_CODES = {
    "jw", "oj", "mj", "aj", "th", "vv", "hat", "hp", "tri", "xm", "xa",
    "oaj", "oajj", "oajjj", "oajjjj",
}


@pytest.mark.parametrize("figure_code", sorted(set(olan_figs) - NOT_OPENAERO - NON_ARESTI_CODES))
def test_open_aero_figure_codes_parse_and_build(figure_code):
    """Every figure code PyOlan reads is an OpenAero figure and builds."""
    figure = OlanFig.take([WRITTEN.get(figure_code, figure_code)])[0]

    assert figure_code in figure.fig.chars.split("|")
    assert figure.create_elements()


def test_the_non_aresti_codes_are_the_pyolan_codes_of_openaero_family_0():
    """NON_ARESTI_CODES is every code PyOlan reads whose OpenAero catalogue number is
    0.x: nothing else is refused as non-Aresti, and none of them is missed."""
    refused = set()
    for code in set(olan_figs) - NOT_OPENAERO:
        try:
            OlanFig.take([WRITTEN.get(code, code)])
        except OlanParseError as ex:
            assert ex.detail == NON_ARESTI
            refused.add(code)

    assert refused == NON_ARESTI_CODES


@pytest.mark.parametrize(
    "olan",
    sorted(
        NON_ARESTI_CODES
        # the inverted and rolling forms OpenAero has (the other inverted codes are
        # not OpenAero figures and raise for that, below)
        | {"4j5-", "4jo5-", "ihat", "ivv", "itri", "ixm", "ixa", "iph", "ibh", "ipbh", "ioj", "34th34"}
    ),
)
def test_an_openaero_non_aresti_figure_raises(olan):
    """Phase S, SQ5: every Family 0 figure is refused under every rule set."""
    with pytest.raises(OlanParseError) as info:
        OlanFig.take([olan])

    assert info.value.detail == NON_ARESTI
    assert info.value.token == olan


@pytest.mark.parametrize(
    "olan", sorted(NOT_OPENAERO) + ["ihp", "iaj", "imj", "ith", "ioaj", "ioajjjj"]
)
def test_a_pyolan_code_openaero_does_not_have_raises(olan):
    with pytest.raises(OlanParseError, match=rf'"{olan}" is not an OpenAero figure'):
        OlanFig.take([olan])


def test_a_figure_with_attitude_markers_openaero_does_not_have_raises():
    with pytest.raises(OlanParseError, match="OpenAero has no figure like this"):
        OlanFig.take(["dz"])  # OpenAero has dz- and -dz only


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
