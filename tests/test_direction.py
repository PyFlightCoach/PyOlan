"""Check PyOlan's exit directions against OpenAero.

tests/data/openaero/sequence_directions.json holds OLAN sequences with the entry and
exit direction and attitude of each figure as OpenAero reports them (direction 0 =
left to right, 90 = front to back, 180 = right to left, 270 = back to front; the
physical heading is reversed when the attitude is 180). It is written by
tools/openaero/export.py from the "[directions]" lines of
tests/data/openaero/regressions.txt, using the pinned OpenAero commit.
"""

import json
from pathlib import Path

import geometry as g
import pytest
import schemas.positioning as p
from pytest import fixture
from tuning.builders import load_builder

from pyolan.direction import physical_to_heading, walk_olan
from pyolan.parser import parse_olan

FIXTURE = json.loads(
    (Path(__file__).parent / "data/openaero/sequence_directions.json").read_text()
)
SEQUENCES = FIXTURE["sequences"]
CASES = [
    pytest.param(seq, id=seq["input"].strip()[:50] or str(i))
    for i, seq in enumerate(SEQUENCES)
]


@fixture(scope="session")
def mb():
    return load_builder("IAC", category="unlimited")


def _physical(direction: int, attitude: int) -> int:
    return (direction + (180 if attitude == 180 else 0)) % 360


def test_fixture_has_open_aero_provenance():
    source = FIXTURE["source"]
    sha = (Path(__file__).parents[1] / "tools/openaero/OPENAERO_SHA").read_text().strip()
    assert source["repository"] == "OpenAero/main"
    assert source["revision"] == sha
    assert source["harness_version"]
    assert SEQUENCES


@pytest.mark.parametrize("seq", CASES)
def test_direction_state_matches_open_aero(seq):
    mine = walk_olan(seq["input"].split())

    assert [m.token for m in mine] == [f["token"] for f in seq["figures"]]
    for m, expected in zip(mine, seq["figures"]):
        assert (m.entry_direction, m.entry_attitude) == (
            expected["entry"]["direction"],
            expected["entry"]["attitude"],
        )
        assert (m.exit_direction, m.exit_attitude) == (
            expected["exit"]["direction"],
            expected["exit"]["attitude"],
        )


# Figures whose template (option 0) is known to leave in the wrong direction.
XFAIL_TEMPLATE: dict[str, str] = {}


_PARSED: dict[str, list] = {}


def _parse(text: str, mb):
    if text not in _PARSED:
        _PARSED[text] = parse_olan(text, mb, p.Heading.LTOR)
    return _PARSED[text]


FIGURE_CASES = [
    pytest.param(
        seq,
        n,
        id=f"{i}-{n}-{fig['token'][:30]}",
    )
    for i, seq in enumerate(SEQUENCES)
    for n, fig in enumerate(seq["figures"])
]


@pytest.mark.parametrize(("seq", "n"), FIGURE_CASES)
def test_parsed_exit_matches_open_aero(request, mb, seq, n):
    wind = p.Heading.LTOR
    parsed = _parse(seq["input"], mb)
    assert [f.olan.token for f in parsed] == [f["token"] for f in seq["figures"]]
    fig, expected = parsed[n], seq["figures"][n]
    heading = physical_to_heading(
        _physical(expected["exit"]["direction"], expected["exit"]["attitude"]), wind
    )

    assert fig.aresti.info.end.direction == p.Direction.parse_heading(heading, wind)
    assert fig.definition.info.end.direction == fig.aresti.info.end.direction

    # option 0 is what the next figure starts from, for an entry along the box
    if fig.aresti.info.start.direction != p.Direction.CROSS:
        if expected["token"] in XFAIL_TEMPLATE:
            request.applymarker(
                pytest.mark.xfail(reason=XFAIL_TEMPLATE[expected["token"]], strict=True)
            )
        # the template leaves in the OLAN exit attitude
        body_z = fig.template.att[-1].transform_point(g.PZ()).z[0]
        assert abs(body_z) > 0.5
        assert (body_z < 0) == (fig.olan.exit == p.Orientation.UPRIGHT)
        assert p.Heading.infer(fig.template.att.bearing()[-1]) == heading
