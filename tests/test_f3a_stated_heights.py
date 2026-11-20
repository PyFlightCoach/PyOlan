"""stated_heights: the start and exit heights the F3A catalogue words state.

Over the 681 entries of the 2026 rulebook fixture, and against the USG drawing
metadata (tests/data/f3a/usg_drawings.json) for agreement.
"""

import json
from collections import Counter
from pathlib import Path

import pytest
import schemas.positioning as p

from pyolan.f3a import stated_heights
from pyolan.f3a.parser import UNRESTRICTED_HEIGHTS

DATA = Path(__file__).parent / "data" / "f3a"
RULEBOOK = json.loads((DATA / "rulebook_2026.json").read_text())
USG = {e["number"]: e for e in json.loads((DATA / "usg_drawings.json").read_text())}
RULEBOOK_TO_USG = {"Q.8": "Q.7", "Q.9": "Q.8"}
USG_HEIGHT = {"low": p.Height.BTM, "middle": p.Height.MID, "high": p.Height.TOP}

BTM, MID, TOP = p.Height.BTM, p.Height.MID, p.Height.TOP
STATED = {e["number"]: stated_heights(e["text"], e["number"]) for e in RULEBOOK}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Knife-edge loop from top (K6)", ({TOP}, None)),
        ("Vertical eight (from middle) (K3)", ({MID}, None)),
        ("Hourglass (middle entry, top first) (K4)", ({MID}, None)),
        ("Rolling loop with one roll (from bottom) (K5)", ({BTM}, None)),
        ("Vertical Knife-edge eight, middle entry and exit, top first (K6)", ({MID}, {MID})),
        ("Square loop (top entry) (K4)", ({TOP}, None)),
        ("Almost 8. From middle inverted, pushed half loop, exit bottom upright (K5)", ({MID}, {BTM})),
        ("Hourglass (K4)", (None, None)),
    ],
)
def test_words(text, expected):
    assert stated_heights(text) == expected


def test_number_must_agree():
    from pyolan.f3a import F3AParseError

    with pytest.raises(F3AParseError):
        stated_heights("01.1 Rolling loop (from bottom) (K5)", "01.2")


def test_every_entry_reads():
    assert len(STATED) == len(RULEBOOK) == 681


def test_stated_set_is_never_empty():
    for number, (entry, exit_) in STATED.items():
        assert entry is None or entry, number
        assert exit_ is None or exit_, number


def test_categories():
    """How many entries fall in each stated category (entry, exit)."""
    counts = Counter(
        (
            tuple(h.name for h in entry) if entry else None,
            tuple(h.name for h in exit_) if exit_ else None,
        )
        for entry, exit_ in STATED.values()
    )
    assert counts == {
        (None, None): 383,
        (("TOP",), None): 179,
        (("BTM",), None): 68,
        (("MID",), None): 42,
        (("MID",), ("MID",)): 1,
        (("BTM",), ("MID",)): 2,
        (("TOP",), ("MID",)): 2,
        (("MID",), ("BTM",)): 2,
        (("MID",), ("TOP",)): 2,
    }


def test_agrees_with_usg_where_usg_states_one():
    """The stated entry, and the stated exit, must match the USG drawing's heights.

    Known disagreements are listed in KNOWN_DISAGREEMENTS (reported, not hidden).
    """
    found = set()
    for number, (entry, exit_) in STATED.items():
        usg = USG[RULEBOOK_TO_USG.get(number, number)]
        if entry is not None and entry != {USG_HEIGHT[usg["entry_height"]]}:
            found.add((number, "entry"))
        if exit_ is not None and exit_ != {USG_HEIGHT[usg["exit_height"]]}:
            found.add((number, "exit"))
    assert found == KNOWN_DISAGREEMENTS


# Reported, not hidden. The words say "from top" but the USG metadata starts at middle for
# the half reverse Cuban eights F.35-F.40, F.61-F.64. The cobra rolls 08.5-08.10 and 14.21
# disagreed too; the A4 review made them unrestricted (UNRESTRICTED_HEIGHTS).
KNOWN_DISAGREEMENTS: set[tuple[str, str]] = {(f"F.{i}", "entry") for i in (*range(35, 41), *range(61, 65))}


def test_unrestricted_entries_are_open_whatever_the_words():
    """A4 review 2026-11-20: go by what is feasible, not the words (the cobra flies TT or MM)."""
    assert UNRESTRICTED_HEIGHTS == {f"08.{i}" for i in range(5, 11)} | {"14.21"}
    for number in UNRESTRICTED_HEIGHTS:
        assert STATED[number] == (None, None)
