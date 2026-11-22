"""Parity of the F3A catalogue with the known schedules (S2 of docs/plans/f3a-catalogue-continuation.md).

``data/f3a/known_schedule_parity.json`` maps figures of the known schedules P25, F25, P27, F27 and A27 to
catalogue entries (``data/f3a/rulebook_2026.json``) where they are the same figure: the same element
sequence, loop angles and roll amounts (rolls and snaps, point-roll stops, reversals) and the same entry
attitude. The known schedules carry no rulebook words, so each pair records the words read from the known
figure's elements next to the rulebook text. The known figure is stored in the fixture (its ``aresti`` form),
so the test needs no database or dataset.

Both are built with the F3A builder (``tuning.builders.load_builder("f3a").create_mdef``) and compared on:

- the element sequence (the kind and name of each element definition, padding lines included),
- the angles, lengths, rolls, ke flags and the comparison parameter (ManParm) each line and loop uses,
- each ManParm: its criteria type, the collectors that feed it and, for roll combinations, the options,
- the centre marks (``centre_points`` and ``centred_els``),
- the manoeuvre info (K, position, entry attitude and heights).

The test asserts that exactly the differences recorded in the fixture appear: a recorded difference that
disappears, or a new one, fails. Every recorded difference carries a reason and a decision (``intended``,
``schedule-specific``, ``bug-suspect`` or ``open`` for the owner to decide). Figures of the known schedules that have no catalogue equivalent are
listed under ``unmatched``.

Run ``python tests/test_f3a_known_parity.py`` from the PyOlan package to print the current differences of every pair.
"""

import json
from pathlib import Path
from uuid import UUID

import pytest
from schemas import aresti as a
from tuning.builders import load_builder

from pyolan.f3a import parse_f3a_description

DATA = Path(__file__).parent / "data" / "f3a"
FIXTURE = json.loads((DATA / "known_schedule_parity.json").read_text())
RULEBOOK = {e["number"]: e for e in json.loads((DATA / "rulebook_2026.json").read_text())}
PAIRS = FIXTURE["pairs"]
DECISIONS = {"intended", "schedule-specific", "bug-suspect", "open"}


@pytest.fixture(scope="module")
def builder():
    return load_builder("f3a")


def catalogue_figure(number: str, member: int) -> a.Figure:
    e = RULEBOOK[number]
    f = parse_f3a_description(f"{number} {e['text']}")
    return f.figures[member] if isinstance(f, a.Option) else f


def known_figure(pair: dict) -> a.Figure:
    return a.Figure.model_validate(pair["known"])


# ---- the signature of a built manoeuvre definition ---------------------------------------------------------------


def _num(v: float) -> float:
    return round(float(v), 4)


def _collectors(mp, pos: dict[str, str]) -> list[str]:
    """The collectors that feed a ManParm, as ``<element>.<element>.<property>.<index>`` with positional names."""
    return [
        ".".join(pos.get(t, t) for t in c.strip().split("."))
        for c in str(mp.collectors).replace("\n", "").split(",")
        if c.strip()
    ]


def _mp_id(mp, pos: dict[str, str]) -> str:
    """A ManParm's identity. Roll and option inputs are named by the schedule's author (``roll_option``, ``opt``,
    ``rspin``), so they are identified by where they are collected; the others by their name."""
    if type(mp.criteria).__name__ == "Combination":
        return f"combination@{_collectors(mp, pos)[0]}"
    try:
        UUID(str(mp.name))
    except ValueError:
        return mp.name
    return f"anonymous@{_collectors(mp, pos)[0]}"  # the builder's own ManParm for a computed length


def _refs(v, pos: dict[str, str], found: set[str]) -> set[str]:
    """The ManParms an operator is built from."""
    if type(v).__name__ == "ManParm":
        found.add(_mp_id(v, pos))
    elif v is not None and hasattr(v, "a"):
        _refs(v.a, pos, found)
        _refs(getattr(v, "b", None), pos, found)
    return found


def _prop(v, pos: dict[str, str]) -> object:
    """A property of an element definition: numbers by value, ManParms and operators by what they refer to."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int | float):
        return _num(v)
    if type(v).__name__ == "ItemOpp":
        return "ItemOpp"  # an item of a roll combination: the ManParm entries below say which
    if type(v).__name__ == "ManParm":
        return f"ManParm:{_mp_id(v, pos)}"
    name = getattr(v, "name", "")
    try:
        UUID(str(name))
        name = ""  # anonymous operator (the builder gives it a uuid)
    except ValueError:
        pass
    return f"{type(v).__name__}:{name}:{'+'.join(sorted(_refs(v, pos, set())))}"


def _rows(desired) -> list:
    """The options of a roll combination as sorted rows of rounded values."""
    return sorted([_num(x) for x in row] for row in desired.tolist())


def signature(mdef) -> dict:
    """What is compared: flat ``path -> value`` for everything listed in the module docstring.

    Elements are identified by their position, not by the builder's name for them (``e_1_roll`` for a roll
    given as an amount, ``e_1_0`` for one given as a list), so the same structure compares equal.
    """
    out: dict[str, object] = {}
    eds = list(mdef.eds)
    pos = {e.name: f"#{i}" for i, e in enumerate(eds)}
    out["elements"] = [e.Kind.__name__ for e in eds]
    for i, e in enumerate(eds):
        for k, v in e.props.items():
            out[f"el.#{i}.{k}"] = _prop(v, pos)
    for mp in mdef.mps.data.values():
        key = f"mp.{_mp_id(mp, pos)}"
        out[f"{key}.criteria"] = type(mp.criteria).__name__
        out[f"{key}.collectors"] = _collectors(mp, pos)
        if getattr(mp.criteria, "desired", None) is not None:
            try:
                out[f"{key}.options"] = _rows(mp.criteria.desired)
            except (AttributeError, TypeError):
                pass
    out["centre_points"] = list(mdef.info.centre_points)
    out["centred_els"] = [[i, _num(f)] for i, f in mdef.info.centred_els]
    i = mdef.info
    out["info.k"] = _num(i.k)
    out["info.position"] = str(i.position)
    out["info.start"] = f"{i.start.orientation.name} {i.start.height.name}"
    out["info.end_height"] = i.end.height.name
    return out


def differences(known: dict, cat: dict) -> list[tuple[str, object, object]]:
    """``(path, known, catalogue)`` of every signature entry that is not equal (a missing entry is None)."""
    if known["elements"] != cat["elements"]:
        # different structures: the per-element entries do not line up, so compare only the structure
        keep = lambda k: not k.startswith(("el.", "mp."))
        known = {k: v for k, v in known.items() if keep(k)}
        cat = {k: v for k, v in cat.items() if keep(k)}
    return [(k, known.get(k), cat.get(k)) for k in sorted(known.keys() | cat.keys()) if known.get(k) != cat.get(k)]


def pair_differences(builder, pair: dict) -> list[tuple[str, object, object]]:
    cat = catalogue_figure(pair["catalogue"]["number"], pair["catalogue"]["member"])
    return differences(signature(builder.create_mdef(known_figure(pair))), signature(builder.create_mdef(cat)))


# ---- tests -------------------------------------------------------------------------------------------------------


def test_fixture_covers_the_known_schedules():
    assert {p["schedule"] for p in PAIRS} <= {"p25", "f25", "p27", "f27", "a27"}
    assert len(PAIRS) == len({p["id"] for p in PAIRS})
    for u in FIXTURE["unmatched"]:
        assert u["schedule"] in {"p25", "f25", "p27", "f27", "a27"} and u["reason"]


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p["id"])
def test_pair_records_its_sources(pair):
    e = RULEBOOK[pair["catalogue"]["number"]]
    assert pair["rulebook"] == e["text"]  # the fixture quotes the rulebook entry it was matched with
    assert pair["words"] and pair["match_basis"] and pair["source"]["file"]
    assert known_figure(pair).info.short_name == pair["short_name"]


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p["id"])
def test_catalogue_matches_the_known_figure(builder, pair):
    got = json.loads(json.dumps(pair_differences(builder, pair)))  # as the fixture stores them
    want = [[d["path"], d["known"], d["catalogue"]] for d in pair["differences"]]
    assert got == want, "differences changed: review them and update the fixture"


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p["id"])
def test_every_difference_is_a_reviewed_decision(pair):
    for d in pair["differences"]:
        assert d["reason"].strip(), d["path"]
        assert d["decision"] in DECISIONS, d["path"]


def test_matched_figures_share_element_kinds(builder):
    """Parity on what matches: the element sequence is the same for every pair unless recorded as a difference."""
    for pair in PAIRS:
        recorded = {d["path"] for d in pair["differences"]}
        cat = signature(builder.create_mdef(catalogue_figure(pair["catalogue"]["number"], pair["catalogue"]["member"])))
        known = signature(builder.create_mdef(known_figure(pair)))
        assert (known["elements"] == cat["elements"]) == ("elements" not in recorded), pair["id"]


if __name__ == "__main__":
    b = load_builder("f3a")
    for p in PAIRS:
        print(f"## {p['id']} -> {p['catalogue']}")
        for d in pair_differences(b, p):
            print("   ", d)
