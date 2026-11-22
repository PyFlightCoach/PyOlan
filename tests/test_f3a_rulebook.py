"""The 2026 rulebook wording of the F3A catalogue against the USG wording.

tests/data/f3a/rulebook_2026.json holds the 681 entries of Annex 5G of the FAI
sporting code (2026 edition, pages 48-73), extracted once from the text of the PDF
(number, text, K; line wraps joined, a hyphen wrap without a space). Numbers are the
rulebook's. The rulebook and the USG list (tests/data/f3a/usg_drawings.json) differ
in the words of a few entries (30.1-30.4 state the pull or push, 30.4 has the typo
"puled", Q.4 states the first loop's sense with the entry) and in the numbering of
group Q (the rulebook's Q.8 and Q.9 are the USG's Q.7 and Q.8), but every entry
must give the same figure, names aside. The review status is in pyolan.f3a.review.
"""

import json
import re
from pathlib import Path

import pytest
from schemas import aresti as a

from pyolan.f3a import F3AParseError, is_reviewed, parse_f3a_description
from pyolan.f3a.normalise import normalise_number
from pyolan.f3a.review import REVIEWED_GROUPS, REVIEWED_NUMBERS

DATA = Path(__file__).parent / "data" / "f3a"
RULEBOOK = json.loads((DATA / "rulebook_2026.json").read_text())
USG = {entry["number"]: entry for entry in json.loads((DATA / "usg_drawings.json").read_text())}
# rulebook number -> USG number, where they differ
RULEBOOK_TO_USG = {"Q.8": "Q.7", "Q.9": "Q.8"}


def _usg_number(number: str) -> str:
    return RULEBOOK_TO_USG.get(number, number)


def _without_names(value):
    if isinstance(value, dict):
        return {k: _without_names(v) for k, v in value.items() if k not in ("name", "short_name")}
    if isinstance(value, list):
        return [_without_names(v) for v in value]
    return value


def _figure(text: str, number: str, k: int | None) -> dict:
    return _without_names(parse_f3a_description(text, number, k).model_dump())


def test_rulebook_fixture():
    numbers = [entry["number"] for entry in RULEBOOK]
    assert len(numbers) == len(set(numbers)) == 681
    assert all(isinstance(entry["k"], int) for entry in RULEBOOK)
    # the USG list has the same entries, numbered as the rulebook but for Q.7/Q.8
    assert {_usg_number(number) for number in numbers} == set(USG)
    for entry in RULEBOOK:  # the text keeps the PDF's spelling, such as "(K 6)"
        assert re.search(rf"\(K\s*{entry['k']}\)", entry["text"]), entry


@pytest.mark.parametrize("entry", RULEBOOK, ids=[entry["number"] for entry in RULEBOOK])
def test_rulebook_entry_matches_usg(entry):
    usg = USG[_usg_number(entry["number"])]
    assert entry["k"] == usg["k"]
    parsed = parse_f3a_description(entry["text"], entry["number"], entry["k"])
    assert isinstance(parsed, a.Figure | a.Option)
    expected = parse_f3a_description(usg["description"], usg["number"], usg["k"])
    assert _without_names(parsed.model_dump()) == _without_names(expected.model_dump())


# ------------------------------------------------------ the five worded differently

# (rulebook number, USG number) pairs whose words differ and that the parser reads as
# the same figure
DIFFERENT_WORDS = ["30.1", "30.2", "30.3", "30.4", "Q.4"]


def test_different_words_are_different():
    """Guard: these are the entries whose rulebook words are not the USG words."""
    for number in DIFFERENT_WORDS:
        rulebook = next(entry for entry in RULEBOOK if entry["number"] == number)["text"]
        assert rulebook.lower() != USG[number]["description"].lower()


def test_diamond_states_pull_and_push():
    text = "Diamond in a loop. From bottom upright, pulled loop with two opposite integrated half-rolls, square loop on corner with half-roll in each leg. Exit upright. (K5)"
    assert _figure(text, "30.1", None) == _figure(USG["30.1"]["description"], "30.1", 5)


@pytest.mark.parametrize("wrong", ["pushed", "pulled"])
def test_diamond_contradicting_sense(wrong):
    # from bottom upright the loop is pulled
    text = f"Diamond in a loop. From {'bottom upright' if wrong == 'pushed' else 'top upright'}, {wrong} loop with two opposite integrated half-rolls, square loop on corner with half-roll in each leg. Exit upright. (K5)"
    with pytest.raises(F3AParseError, match="loop, not a"):
        parse_f3a_description(text, "30.1")


def test_diamond_typo_and_wrap():
    base = "Diamond in a loop. From top inverted, {} loop with two opposite integrated half-{}rolls, square loop on corner with half-roll in each leg. Exit inverted. (K5)"
    expected = _figure(USG["30.4"]["description"], "30.4", 5)
    for loop, wrap in (("puled", ""), ("pulled", " "), ("pulled", "")):
        assert _figure(base.format(loop, wrap), "30.4", None) == expected


def test_almost_eight_first_loop_stated_with_entry():
    text = "Almost 8. From top upright pushed, half loop, pulled half loop with 1/2 roll integrated, pushed half loop, exit middle upright (K4)"
    assert _figure(text, "Q.4", None) == _figure(USG["Q.4"]["description"], "Q.4", 4)
    # a plain half loop needs the sense stated with the entry, and only the first one does
    with pytest.raises(F3AParseError):
        parse_f3a_description(
            "Almost 8. From top upright, half loop, pulled half loop with 1/2 roll integrated, "
            "pushed half loop, exit middle upright",
            "Q.4",
        )
    with pytest.raises(F3AParseError):
        parse_f3a_description(
            "Almost 8. From top upright pushed, half loop, half loop with 1/2 roll integrated, "
            "pushed half loop, exit middle upright",
            "Q.4",
        )


# --------------------------------------------------------------- review status


def test_reviewed_groups_and_numbers():
    groups = {entry["number"].split(".")[0] for entry in RULEBOOK}
    assert REVIEWED_GROUPS <= groups
    # every group (catalogue review 2026-11-21; J on 2026-11-22)
    assert REVIEWED_GROUPS == groups
    assert {entry["number"] for entry in RULEBOOK} >= REVIEWED_NUMBERS == {"23.15", "23.16"}


def test_is_reviewed_counts():
    reviewed = [entry["number"] for entry in RULEBOOK if is_reviewed(entry["number"])]
    assert all(number.split(".")[0] in REVIEWED_GROUPS or number in REVIEWED_NUMBERS for number in reviewed)
    by_group = {}
    for entry in RULEBOOK:
        by_group.setdefault(entry["number"].split(".")[0], []).append(entry["number"])
    expected = sum(len(by_group[group]) for group in REVIEWED_GROUPS)
    assert len(reviewed) == expected == 681


@pytest.mark.parametrize(
    "number",
    ["01.1", "1.1", "09.6", "22.12", "26.8", "23.15", "23.16", "23.1", "24.1", "25.6", "28.4",
     "30.4", "A.1", "K.1", "L.7", "P.6", "P.12", "Q.9", "E.63", "F.63"],
)
def test_reviewed(number):
    assert is_reviewed(number)


@pytest.mark.parametrize("number", ["J.1", "J.34", "J.44"])
def test_unreviewed(number, monkeypatch):
    # every group is reviewed: without the group list only REVIEWED_NUMBERS count
    import pyolan.f3a.review as review

    monkeypatch.setattr(review, "REVIEWED_GROUPS", frozenset())
    assert not is_reviewed(number)
    assert is_reviewed("23.15")


def test_is_reviewed_number_forms():
    assert is_reviewed(" 1.9 ") == is_reviewed("01.9")
    assert is_reviewed("j.1") == is_reviewed("J.1") is True
    with pytest.raises(F3AParseError):
        is_reviewed("not a number")
    assert normalise_number("1.9") == "01.9"
