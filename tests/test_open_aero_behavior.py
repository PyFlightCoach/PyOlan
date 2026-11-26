import numpy as np
import pytest
from schemas.positioning import Direction, Orientation

from pyolan.drawing import re_draw
from pyolan.figure_parser import OlanFig


@pytest.mark.parametrize(
    ("figure_code", "expected_rolls"),
    [
        ("d1", [None, [1.0], None]),
        ("d2f", [None, [0.5], None]),
        ("d2,2", [None, [0.5, -0.5], None]),
        ("o22", [[0.5, 0.5]]),
        ("n(3f,3.)", [None, None, None, [0.75, -0.75], None, None, None]),
    ],
)
def test_open_aero_rolls_are_attached_to_the_expected_elements(
    figure_code, expected_rolls
):
    figure = OlanFig.take([figure_code])[0]
    actual_rolls = [
        roll.turns() if roll is not None else None
        for roll in figure.element_rolls()
    ]

    assert actual_rolls == expected_rolls


@pytest.mark.parametrize(
    ("figure_code", "expected_rolls", "expected_types"),
    [
        ("d2f", [0.5], "snap"),
        ("d2,2", [0.5, -0.5], "roll"),
        ("o22", [0.5, 0.5], "roll"),
        ("d1s", [1.0], "spin"),
        ("d1is", [1.0], "spin"),
    ],
)
def test_open_aero_rolls_preserve_type_and_angle(
    figure_code, expected_rolls, expected_types
):
    figure = OlanFig.take([figure_code])[0]
    roll = next(roll for roll in figure.element_rolls() if roll is not None)

    assert roll.turns() == expected_rolls
    assert roll.rolltypes() == expected_types


@pytest.mark.parametrize(
    ("figure_code", "entry", "exit"),
    [
        ("o", Orientation.UPRIGHT, Orientation.UPRIGHT),
        ("-o", Orientation.INVERTED, Orientation.UPRIGHT),
        ("o-", Orientation.UPRIGHT, Orientation.INVERTED),
        ("-o-", Orientation.INVERTED, Orientation.INVERTED),
        ("-ry-", Orientation.INVERTED, Orientation.INVERTED),
    ],
)
def test_open_aero_attitude_markers(figure_code, entry, exit):
    figure = OlanFig.take([figure_code])[0]

    assert figure.entry == entry
    assert figure.exit == exit


@pytest.mark.parametrize(
    ("figure_code", "expected_loops"),
    [
        ("o", [1.0]),
        ("-o", [-1.0]),
        ("ry", [0.25, 0.0, 0.625, 0.0, 0.125]),
        ("-ry", [-0.25, 0.0, 0.625, 0.0, 0.125]),
        ("ry-", [0.25, 0.0, -0.625, 0.0, -0.125]),
    ],
)
def test_open_aero_attitude_changes_loop_directions(figure_code, expected_loops):
    figure = OlanFig.take([figure_code])[0]

    np.testing.assert_allclose(
        figure.loop_amounts(figure.element_rolls()), expected_loops
    )


@pytest.mark.parametrize(
    ("drawing", "expected_direction"),
    [
        ("eu", Direction.UPWIND),
        ("ed", Direction.DOWNWIND),
        ("ej", Direction.CROSS),
        ("eja", Direction.CROSS),
    ],
)
def test_open_aero_entry_direction_drawing_commands(
    drawing, expected_direction
):
    figure = OlanFig.take([drawing, "d"])[0]

    assert figure.entry_direction == expected_direction
    assert figure.draw == [drawing]


def test_open_aero_vertical_exit_marker_is_preserved():
    figure = OlanFig.take([">d"])[0]

    assert figure.token == ">d"
    assert re_draw.sub("", figure.rawfig) == "d"


def test_open_aero_drawing_commands_are_removed_without_changing_rolls():
    drawn = OlanFig.take(["/~~+++..''1.'n('5if,3.).,8.---~"])[0]

    assert drawn.fig.chars == "n"
    assert [
        roll.turns() if roll is not None else None
        for roll in drawn.element_rolls()
    ] == [None, [1], None, [1.25, -0.75], None, [-0.125, -0.125], None]  # ",8": F23


def test_open_aero_roll_only_fields_are_supported():
    for code in ("1", "22", "4f", "5if", "9s", "9is"):
        figure = OlanFig.take([code])[0]

        assert figure.create_elements()


@pytest.mark.parametrize("invalid", ["", "unknown", "100%", "("])
def test_invalid_open_aero_tokens_are_rejected(invalid):
    with pytest.raises(Exception):
        OlanFig.take([invalid])


def test_open_aero_sequences_accept_mixed_whitespace():
    figures = "ed\td  \n  ej o\u00a0d".split()

    parsed = []
    remaining = figures
    while remaining:
        figure, remaining = OlanFig.take(remaining)
        parsed.append(figure)

    assert [figure.fig.chars for figure in parsed] == ["d", "o", "d"]
