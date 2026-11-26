"""No silent drops (plan B5, D7).

Anything PyOlan cannot read must raise OlanParseError naming the item, never be
skipped. (Every figure that OpenAero builds must become a PyOlan figure: the
"missing" check of test_sequence in test_openaero_strict.py.)
"""

import random

import pytest

from pyolan.direction import parse_rolls
from pyolan.errors import OlanParseError
from pyolan.parser import parse_olan
from pyolan.rolls import OlanRoll

pytestmark = pytest.mark.component


@pytest.mark.parametrize(
    "text, token, index, figure",
    [("o 2x o", "2x", 1, 2), ("o 4h4 ?q o", "?q", 2, 3), ("ed o qz o", "qz", 2, 2)],
)
def test_parse_olan_raises_on_an_unreadable_token(text, token, index, figure):
    from tuning.builders import load_builder

    with pytest.raises(OlanParseError) as info:
        parse_olan(text, load_builder("IAC", category="unlimited"))
    assert (info.value.token, info.value.index, info.value.figure) == (token, index, figure)
    assert info.value.message.startswith(f'Figure {figure} "{token}": ')


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


@pytest.mark.parametrize("text", ["1x", "2;q", "4,0", "22;?", "1;2z"])
def test_roll_parse_rejects_an_unreadable_piece(text):
    with pytest.raises(OlanParseError):
        OlanRoll.parse(text)
