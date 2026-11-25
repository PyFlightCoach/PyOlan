"""No silent drops (plan B5, D7).

Every figure that OpenAero builds must become a PyOlan figure, and anything PyOlan
cannot read must raise an error that names the token, never be skipped. These are
strict xfails until C2 (findings F2 and F5) lands.
"""

import random
import sys
from pathlib import Path

import pytest
from loguru import logger

from pyolan.direction import parse_rolls
from pyolan.parser import parse_olan
from pyolan.rolls import OlanRoll

sys.path.insert(0, str(Path(__file__).parent))
from openaero import differential as D  # noqa: E402

pytestmark = pytest.mark.component

C2 = pytest.mark.xfail(strict=True, reason="F2, F5: figures dropped silently until C2")


@C2
@pytest.mark.parametrize("corpus", D.CORPORA)
def test_every_openaero_figure_is_built(corpus):
    logger.disable("pyolan")
    try:
        res = D.differences(corpus, ("missing",))
    finally:
        logger.enable("pyolan")
    expected = D.known_set(("missing",), corpus)
    assert res.diffs == expected, D.report(res, expected)


@C2
@pytest.mark.parametrize("text", ["o 2x o", "o 4h4 ?q o", "o qz o"])
def test_parse_olan_raises_on_an_unreadable_token(text):
    from tuning.builders import load_builder

    with pytest.raises(ValueError):
        parse_olan(text, load_builder("IAC", category="unlimited"))


# ---------------------------------------------------------------------------
# OlanRoll.parse: every piece is used or rejected

PIECES = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "22", "24", "34", "44", "48", "88",
          "1f", "2f", "1if", "2if", "3if", "5if", "6f", "1s", "1is", "5s", "6is", "f", "if"]


def _roll_strings(seed: int, n: int) -> list[str]:
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        parts = [rng.choice(PIECES) for _ in range(rng.randint(1, 4))]
        text = parts[0]
        for part in parts[1:]:
            text += rng.choice([";", ","]) + part
        out.append(text)
    return out


@pytest.mark.parametrize("text", _roll_strings(1, 60))
def test_roll_parse_uses_every_piece(text):
    """The total roll equals OpenAero's (direction.parse_rolls mirrors its parser)."""
    roll = OlanRoll.parse(text)
    oa_total = sum(abs(r.extent) for r in parse_rolls(text)[0]) / 360
    assert sum(abs(t) for t in roll.turns()) == pytest.approx(oa_total)


@C2
@pytest.mark.parametrize("text", ["1x", "2;q", "4,0", "22;?", "1;2z"])
def test_roll_parse_rejects_an_unreadable_piece(text):
    with pytest.raises(ValueError):
        OlanRoll.parse(text)
