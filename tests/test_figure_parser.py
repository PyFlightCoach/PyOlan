import pytest
import numpy as np
import schemas.aresti as a
from schemas.positioning import Orientation

from pyolan.errors import OlanParseError
from pyolan.figure_parser import OlanFig
from pyolan.rolls import ro, sn, spi


def test_olan_take() -> OlanFig:
    data = "2% `````4,3if``ry.'22 /~~+++..''1.'n('5if,3.).,8.---~".split(" ")
    ofig, newdata = OlanFig.take(data)

    assert isinstance(ofig, OlanFig)
    assert len(newdata) < len(data) and len(newdata) > 0

    assert ofig.fig.chars == "ry"

    assert ofig.prefix.roll_arr == [ro(1 / 4), sn(-3 / 4, True)]
    assert ofig.final.roll_arr == [ro(1 / 2), ro(1 / 2)]
    assert not ofig.suffix
    assert ofig.entry == Orientation.UPRIGHT
    assert ofig.exit == Orientation.UPRIGHT


def test_olan_take_with_drawing():
    ofig = OlanFig.take(["/~~+++..''1.'n('5if,3.).,8.---~"])[0]

    assert ofig.entry == Orientation.UPRIGHT
    assert ofig.exit == Orientation.INVERTED
    assert ofig.fig.chars == "n"
    assert ofig.prefix.roll_arr == [ro(1)]

    pass


def test_olan_take_with_drawing_2():
    ofig = OlanFig.take(["(-8,14)", "4%", "'',22m2"])[0]
    assert len(ofig.draw) == 2


def test_element_rolls():
    ofig = OlanFig.take(["/~~+++..''1.'n('5if,3.).,8.---~"])[0]
    rolls = [r.roll_arr if r else None for r in ofig.element_rolls()]
    assert not rolls[0]
    assert rolls[1] == [ro(1)]
    assert not rolls[2]
    assert rolls[3] == [sn(5 / 4, True), ro(-3 / 4)]
    assert not rolls[4]
    assert rolls[5] == [ro(-1 / 8), ro(-1 / 8)]  # a leading "," reverses the roll (F23)

    ofig2 = OlanFig.take(["(13,8)", "-```5is';3..''iBb(``````````4',2`)....1~~"])[0]
    rolls = ofig2.element_rolls()
    assert rolls[1].roll_arr == [spi(5 / 4, True), ro(3 / 4)]


def test_3_element_rolls():
    fig = OlanFig.take(["2w(4)2"])[0]
    rolls = [r.total() if r else 0 for r in fig.element_rolls()]
    assert rolls == [0, 0.5, 0, 0.25, 0, 0.5, 0]


def test_fig_n_rolls():
    fig = OlanFig.take(["-.'pn(3f,3.')."])[0]
    rolls = [r.turns() if r else [] for r in fig.element_rolls()]
    assert rolls == [[], [], [], [3 / 4, -3 / 4], [], [], []]


def loop_amount_check(elstr, expected):
    oel = OlanFig.take([elstr])[0]
    np.testing.assert_array_equal(oel.loop_amounts(oel.element_rolls()), expected)


def test_loop_amounts():
    loop_amount_check("2pb2", [0.25, 0, -0.5, 0, 0.25])
    loop_amount_check("-2pb2", [-0.25, 0, -0.5, 0, 0.25])
    loop_amount_check("2pb2-", [0.25, 0, -0.5, 0, -0.25])
    loop_amount_check("-2pb2-", [-0.25, 0, -0.5, 0, -0.25])
    loop_amount_check("w", [1 / 8, 0, -3 / 8, 0, 3 / 8, 0, -1 / 8])
    loop_amount_check("w-", [1 / 8, 0, -3 / 8, 0, -3 / 8, 0, 1 / 8])
    loop_amount_check("ry", [1 / 4, 0, 5 / 8, 0, 1 / 8])
    loop_amount_check("ry-", [1 / 4, 0, -5 / 8, 0, -1 / 8])
    loop_amount_check("-ry", [-1 / 4, 0, 5 / 8, 0, 1 / 8])
    loop_amount_check("-ry-", [-1 / 4, 0, -5 / 8, 0, -1 / 8])
    loop_amount_check("n", [1 / 4, 0, 3 / 8, 0, -3 / 8, 0, -1 / 4])
    loop_amount_check("n-", [1 / 4, 0, 3 / 8, 0, -3 / 8, 0, 1 / 4])
    loop_amount_check("-n", [-1 / 4, 0, 3 / 8, 0, -3 / 8, 0, -1 / 4])
    loop_amount_check("-w", [-1 / 8, 0, 3 / 8, 0, 3 / 8, 0, -1 / 8])
    loop_amount_check("-2w(4)2", [-1 / 8, 0, -3 / 8, 0, -3 / 8, 0, -1 / 8])
    loop_amount_check("-2pb3,1if", [-1 / 4, 0, -1 / 2, 0, 1 / 4])
    loop_amount_check(
        "/~~+++..''1.'n('5if,3.).,8.---~", [1 / 4, 0, 3 / 8, 0, 3 / 8, 0, 1 / 4]
    )
    loop_amount_check(
        "-```5is';3..''iBb(``````````4',2`)....1~~",
        [1 / 4, 0, 1 / 2, 0, 1 / 2, 0, 1 / 4],
    )
    loop_amount_check("ib", [-0.25, 0, 0.5, 0, -0.25])


def test_q_loops():
    loop_amount_check("2q2", [0, -7 / 8, 0, 1 / 8])
    loop_amount_check("-q-", [0, -7 / 8, 0, -1 / 8])
    loop_amount_check("q", [0, 7 / 8, 0, 1 / 8])


def test_single_loop_amount():
    loop_amount_check("of", [1])


def test_olan_take_dhump():
    ofig = OlanFig.take(["-```5is';3..''iBb(``````````4',2`)....1~~"])[0]

    assert ofig.entry == Orientation.INVERTED
    assert ofig.exit == Orientation.UPRIGHT


def test_create_elements(olan_teardrop):
    pes = OlanFig.take([olan_teardrop])
    aresti = pes[0].create_elements()

    assert isinstance(aresti[0], a.PE)


def test_create_avalanche():
    ofig = OlanFig.take(["of2"])[0]
    pe = ofig.create_elements()
    assert len(pe) == 1


def test_olan_take_only_roll():
    ofig = OlanFig.take(["22"])[0]
    els = ofig.create_elements()
    assert len(els) == 1
    assert isinstance(els[0], a.PE)


def test_marker_only_roll_slot_is_treated_as_no_roll():
    ofig = OlanFig.take(["+o_+"])[0]

    assert ofig.element_rolls()[0].roll_arr == []
    assert [(element.kind, element.args, element.kwargs) for element in ofig.create_elements()] == [
        ("loop", [2 * np.pi], {})
    ]


def test_create_roll_element_preserves_roll_metadata():
    element = OlanFig.take(["22"])[0].create_elements()[0]

    assert element.kind == "roll"
    assert element.args == ["2x2"]
    assert element.kwargs == {"rolltypes": "roll", "padded": False}


def test_olan_take_turn():
    ofig = OlanFig.take(["j"])[0]
    els = ofig.create_elements()
    assert len(els) == 3


def test_create_rolling_turn_preserves_angles_and_ke():
    for code, expected_rolls in [
        # "5" is a half roll, as OpenAero reads it (F17; was five rolls)
        ("1j5-", [np.radians(180)]),
        ("1jo5-", [np.radians(-180)]),
    ]:
        element = OlanFig.take([code])[0].create_elements()[0]

        assert element.kind == "loop"
        assert element.args == [np.radians(90)]
        np.testing.assert_allclose(element.kwargs["rolls"], expected_rolls[0])
        assert element.kwargs["ke"] == np.radians(90)


def test_olan_take_turn_2():
    ofig = OlanFig.take("3% 10> 4joi2>".split(" "))[0]
    assert ofig.fig.oels[0].turnamount == 1
    assert ofig.final.roll_arr == [ro(-1), ro(1)]


def test_olan_take_compound_rolling_turn_variants():
    cases = [
        # rolls that end inverted are written with "-" after them (OpenAero has no
        # figure otherwise, F19)
        # each digit is rolls, "5" a half roll; io and oi alternate every roll
        # (F17: these were 5, -5, [1.5, 0.5], [-1.5, 0.5], [1, 0.5], [-1, 0.5])
        ("1j5-", "i", 1 / 4, [ro(0.5)]),
        ("1jo5-", "o", 1 / 4, [ro(-0.5)]),
        ("2j15-", "i", 1 / 2, [ro(1.5)]),
        ("2jo15-", "o", 1 / 2, [ro(-1.5)]),
        ("2jio15-", "io", 1 / 2, [ro(1), ro(-0.5)]),
        ("2joi15-", "oi", 1 / 2, [ro(-1), ro(0.5)]),
        ("2jio51-", "io", 1 / 2, [ro(0.5), ro(-1)]),
        ("3jio3", "io", 3 / 4, [ro(1), ro(-1), ro(1)]),
        ("4jio3", "io", 1, [ro(1), ro(-1), ro(1)]),
        ("4joi4", "oi", 1, [ro(-1), ro(1), ro(-1), ro(1)]),
    ]

    for code, rolltype, turnamount, expected_rolls in cases:
        ofig = OlanFig.take([code])[0]

        assert ofig.fig.oels[0].rolltype == rolltype
        assert ofig.fig.oels[0].turnamount == turnamount
        assert ofig.element_rolls()[0].roll_arr == expected_rolls


def test_olan_take_spin():
    # OpenAero's iv downline with the spin on it (F7, F24)
    ofig = OlanFig.take(["s"])[0]
    assert len(ofig.fig.oels) == 3
    assert ofig.final.roll_arr[0].turns == 1
    loop_amounts = ofig.loop_amounts(ofig.element_rolls())
    np.testing.assert_array_equal(loop_amounts, [-0.25, 0, 0.25])


def test_create_spin_elements_preserves_spin_angle_and_following_geometry():
    elements = OlanFig.take(["s"])[0].create_elements()

    assert [(element.kind, element.args) for element in elements] == [
        ("spin", [np.radians(360)]),
        ("line", []),
        ("loop", [np.radians(90)]),
    ]


@pytest.mark.parametrize("code", ["-ivis", "-iv1is", "-is", "-1is"])
def test_bare_inverted_spin_is_one_turn(code):
    # OpenAero reads a bare spin letter as one turn; "-ivis" is the iv downline
    # with an inverted spin, not a figure of its own.
    ofig = OlanFig.take([code])[0]
    assert (ofig.entry, ofig.exit) == (Orientation.INVERTED, Orientation.UPRIGHT)
    assert [(element.kind, element.args) for element in ofig.create_elements()] == [
        ("spin", [pytest.approx(2 * np.pi)]),
        ("line", []),
        ("loop", [pytest.approx(np.pi / 2)]),
    ]


@pytest.mark.parametrize("code", ["df", "dif", "ivf", "ivif"])
def test_bare_snap_on_line_is_kept(code):
    elements = OlanFig.take([code])[0].create_elements()
    assert [element.kind for element in elements] == ["loop", "roll", "loop"]
    assert elements[1].args == [pytest.approx(2 * np.pi)]
    assert elements[1].kwargs["rolltypes"] == "snap"


def test_create_stallturn_and_tailslide_directions():
    stallturn = OlanFig.take(["h"])[0].create_elements()[2]
    tailslides = [
        OlanFig.take([code])[0].create_elements()[2] for code in ("ta", "ita")
    ]

    assert stallturn.kind == "stallturn"
    assert stallturn.args == []
    assert [element.kind for element in tailslides] == ["tailslide", "tailslide"]
    assert [element.args for element in tailslides] == [[1], [-1]]


def test_create_unl_loop():
    ofig = OlanFig.take(["o8;5f-"])[0]
    els = ofig.create_elements()
    pass


def test_create_spin_on_line():
    fig = OlanFig.take(["```9s....'ikz----~~"])[0]
    aresti = fig.create_elements()
    assert aresti[0].kind == "spin"


def test_imac_adv_reversing_loop():
    fig = OlanFig.take(["48,2rpp(,f)2"])[0]
    assert fig.fig.chars == "rpp"


def test_path_angles_follow_the_geometric_path():
    # p(2): a 3/4 loop carrying a half roll, a line, then a 1/4 loop. The half roll
    # moves the canopy, so the last loop (+1/4 pull) brings the path back to level.
    fig = OlanFig.take(["p(2)"])[0]
    rolls = fig.element_rolls()
    loops = fig.loop_amounts(rolls)

    angles, canopies = fig.path_angles(loops, rolls)

    np.testing.assert_allclose(angles, [0, 0, 0.75, 0.75, 0.5])
    np.testing.assert_array_equal(canopies, [1, 1, -1, -1, -1])
    assert fig.exit_attitude(loops, rolls) == fig.exit


def test_path_angles_inverted_entry_descends_on_a_pull():
    fig = OlanFig.take(["ip(2)"])[0]
    rolls = fig.element_rolls()
    angles, canopies = fig.path_angles(fig.loop_amounts(rolls), rolls)

    np.testing.assert_allclose(angles, [0, 0, -0.75, -0.75, -0.5])
    np.testing.assert_array_equal(canopies, [1, 1, -1, -1, -1])


@pytest.mark.parametrize(
    "code", ["c", "-c", "rc", "g", "q", "mm", "dq", "db", "cc", "ac", "xa", "aj", "d", "o"]
)
def test_inverted_figure_without_a_vertical_is_mirrored(code):
    # "i" mirrors the whole figure top to bottom when no vertical line resets it
    plain = OlanFig.take([code])[0]
    inverted = OlanFig.take([code.replace(code.lstrip("-"), "i" + code.lstrip("-"))])[0]
    np.testing.assert_allclose(
        inverted.loop_amounts(inverted.element_rolls()),
        -plain.loop_amounts(plain.element_rolls()),
    )


def test_half_cuban_from_the_top_after_an_entry_snap():
    # 1.5 snap leaves the aircraft inverted, so the "ic" 5/8 loop is pulled down,
    # then a half roll on the 45 upline and a pull to level inverted. The leading
    # "," reverses the snap (F23).
    ofig = OlanFig.take([",6fic2-"])[0]
    assert [(e.kind, e.args) for e in ofig.create_elements()] == [
        ("roll", [pytest.approx(-3 * np.pi)]),
        ("loop", [pytest.approx(5 * np.pi / 4)]),
        ("roll", [pytest.approx(np.pi)]),
        ("loop", [pytest.approx(np.pi / 4)]),
    ]


@pytest.mark.parametrize("code, turns, negative", [("6s", 1.5, False), ("+5s", 1.25, False), ("-5is", 1.25, True), ("s", 1, False)])
def test_spin_with_no_figure_is_a_spin(code, turns, negative):
    """F7: OpenAero's iv downline with the spin; the turns are a spin roll on it."""
    fig = OlanFig.take([code])[0]
    assert (fig.fig.name, fig.fig.short_name) == ("Spin", "sp")
    roll = fig.element_rolls()[1].roll_arr
    assert [(r.kind, r.turns, r.negative) for r in roll] == [("spin", turns, negative)]
    assert fig.create_elements()[0].kind == "spin"


@pytest.mark.parametrize(
    "code, entry, exit_, kinds, k",
    [
        ("--", "INVERTED", "INVERTED", ["line"], 3),  # 1.1.1.2
        ("---", "INVERTED", "INVERTED", ["line"], 3),
        ("-", "INVERTED", "UPRIGHT", ["roll"], 6),  # 1.1.1.4 with OpenAero's half roll
        ("''-", "INVERTED", "UPRIGHT", ["roll"], 6),
    ],
)
def test_a_line_with_attitude_markers_is_a_line_figure(code, entry, exit_, kinds, k):
    """F21: OpenAero's horizontal line figures."""
    fig = OlanFig.take([code])[0]
    assert (fig.entry.name, fig.exit.name) == (entry, exit_)
    assert [e.kind for e in fig.create_elements()] == kinds
    assert fig.k_factor() == k
    assert bool(fig.warnings) == (exit_ == "UPRIGHT")


@pytest.mark.parametrize("code", ["+3jio15++", "3jio15", "1j5", "-2j"])
def test_a_turn_openaero_rejects_raises(code):
    """F19: no catalogue figure, so OpenAero builds nothing."""
    with pytest.raises(OlanParseError, match="OpenAero has no turn or rolling turn like this"):
        OlanFig.take([code])


@pytest.mark.parametrize("olan, exit_heading", [("+5s", "INTOOUT"), ("ed +5s", "INTOOUT")])
def test_a_bare_quarter_spin_exits_as_openaero_draws_it(olan, exit_heading):
    """F24: a 1 1/4 spin with no figure turns the way OpenAero draws it."""
    from pyolan.parser import parse_olan
    from schemas.positioning import Heading
    from tuning.builders import load_builder

    fig = parse_olan(olan, load_builder("IAC", category="unlimited"), Heading.RTOL)[-1]
    assert Heading.infer(fig.template.att.bearing()[-1]).name == exit_heading
