"""Names and short names of the F3A catalogue figures (pyolan.f3a.names).

``data/f3a/catalogue_names.json`` holds the name of every catalogue entry, as reviewed. Rebuild it
after a deliberate change with ``python tests/test_f3a_names.py`` and review the diff.
"""

import json
import keyword
import sys
from pathlib import Path

import pytest

from pyolan.f3a import parse_f3a_description
from pyolan.f3a.names import MAX_LENGTH, catalogue_names
from pyolan.f3a.normalise import split_description
from pyolan.f3a.parser import apply_errata

DATA = Path(__file__).parent / "data" / "f3a"
RULEBOOK = json.loads((DATA / "rulebook_2026.json").read_text())
NAMES_FILE = DATA / "catalogue_names.json"


def names_of(entry: dict) -> tuple[str, str]:
    return catalogue_names(apply_errata(split_description(entry["text"], entry["number"])))


def build_names() -> list[dict]:
    return [
        {"number": e["number"], "name": n, "short_name": s, "description": e["text"]}
        for e in RULEBOOK
        for n, s in [names_of(e)]
    ]


@pytest.mark.parametrize(
    "number, name, short_name",
    [
        ("15.13", "Square Vertical Eight", "sqV8"),
        ("22.11", "Rolling Circle, 4 rolls out", "rCirc"),
        ("J.1", "Top Hat, 3/4 up, 1/4 down", "tHat"),
        ("18.1", "Humpty, 1/2 up, 2/4pt down", "humpty"),
        ("23.9", "Two 3/4pt Rolls Reversed", "rollC"),
        ("19.4", "2 Turn Opposite Spin", "spin"),
        ("19.9", "2 1/4 Turn Spin", "spin"),  # cut at a clause that fits
        ("N.5", "Half Sq Loop on Corner, Down", "hSqLC"),
        ("A.20", "Half Square Loop, roll down", "hSqL"),
        ("01.9", "Knife-Edge Loop", "keLoop"),  # "from top" is in ManInfo
    ],
)
def test_examples(number, name, short_name):
    entry = next(e for e in RULEBOOK if e["number"] == number)
    assert names_of(entry) == (name, short_name)


def test_every_entry_has_a_family_and_names_that_fit():
    for entry in RULEBOOK:
        name, short_name = names_of(entry)
        assert 0 < len(name) <= MAX_LENGTH, entry
        assert short_name.isidentifier() and not keyword.iskeyword(short_name), entry
        assert len(short_name) <= 8 and short_name != "f3a", entry


def test_parsed_figures_carry_the_names():
    fig = parse_f3a_description("22.11 Rolling circle with 4 rolls outside (K5)")
    assert (fig.info.name, fig.info.short_name) == ("Rolling Circle, 4 rolls out", "rCirc")


def test_names_match_the_reviewed_file():
    assert build_names() == json.loads(NAMES_FILE.read_text())


if __name__ == "__main__" and sys.argv[1:] == []:
    NAMES_FILE.write_text(json.dumps(build_names(), indent=1, ensure_ascii=False) + "\n")
