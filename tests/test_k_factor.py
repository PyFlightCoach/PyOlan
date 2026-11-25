"""K as OpenAero computes it (plan C3, D8): the catalogue K of the variant OpenAero
chooses plus each roll's K, keyed by attitude and roll pattern. Values from the
pinned OpenAero (tools/openaero, harness traces)."""

import pytest

from pyolan.errors import OlanParseError
from pyolan.figure_parser import OlanFig


@pytest.mark.parametrize(
    "token, aresti, powered, glider",
    [
        ("d", ["1.1.2.1"], 7, 7),  # was 10: 1.1.5.1 was chosen
        ("1", ["1.1.1.1", "9.1.3.4"], 10, 14),
        ("iv.s.", ["1.1.6.3", "9.11.1.4"], 15, 15),  # raised, then 10
        ("+++2j+++~", ["2.2.1.1"], 4, 4),  # raised, then 10
        ("of2", ["7.4.1.1", "9.9.3.4", "9.1.3.2", "9.1.3.2"], 29, 38),  # with the correction roll
        ("2,24ta3if", ["6.2.1.1", "9.1.1.2", "9.4.1.2", "9.10.5.3"], 45, 60),
        ("1ifjw2,2", ["0.0", "9.10.7.4", "9.1.4.2", "9.1.4.2"], 33, 37),  # rolls after a wingover
        ("24-", ["1.1.1.3", "9.4.3.2"], 7, 10),  # F14: a two point half roll
        ("4;4-", ["1.1.1.3", "9.1.3.1", "9.1.3.1"], 6, 8),  # and two quarter rolls
    ],
)
def test_k_matches_openaero(token, aresti, powered, glider):
    fig = OlanFig.take([token])[0]
    assert fig.openaero().aresti == aresti
    assert (fig.k_powered, fig.k_glider) == (powered, glider)
    assert fig.create_maninfo().k == powered


def test_a_figure_openaero_does_not_have_has_no_k():
    fig = OlanFig.take(["3jio15"])[0]  # one and a half rolls need an inverted exit
    with pytest.raises(OlanParseError, match="no K"):
        fig.k_factor()
