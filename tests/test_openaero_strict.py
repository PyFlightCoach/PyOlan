"""PyOlan against OpenAero, one test per item (PyOlan component lane).

Each corpus in tests/data/openaero/expected holds OpenAero's own trace of every
figure, reduced to the canonical form (tests/openaero/canonical.py). There is no
list of accepted differences: every difference from OpenAero is a failing test. The
two deliberate exceptions are expected errors: a sequence that does not link (D2) and
OpenAero's non-Aresti figures, its Family 0 with the point tip (D11, Phase S SQ5).

* ``test_figure[<corpus>:<figure string>]``: elements, negative flags, entry and
  exit attitude, errors, powered and glider K;
* ``test_sequence[<corpus>:<sequence id>]``: direction state, figures OpenAero
  builds that PyOlan does not (missing) and the reverse (extra);
* ``test_template[<sequence id>]``: parse_olan templates against OpenAero's figure
  exits, and no heading override warning, for the fixed subset in
  tests/data/openaero/template_subset.json;
* ``test_template_other_rules[<rules>:<sequence id>]``: the same under CIVA, IMAC,
  IACGlider and CIVAGlider, for a smaller part of the subset;
* ``test_template_library_all``: the same for every library sequence (about four
  minutes). It is a diagnostic selection, not part of the component lane:

    .venv/bin/python scripts/test.py diagnostic --package PyOlan \\
        --select packages/PyOlan/tests/test_openaero_strict.py::test_template_library_all

Refresh the expectations with tools/openaero/export.py and group the failures by
finding with tools/openaero/propose_findings.py.
"""

import json
import sys
from functools import lru_cache
from pathlib import Path

import pytest
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))
from openaero import differential as D  # noqa: E402
from openaero import templates as T  # noqa: E402

pytestmark = pytest.mark.component

_SUBSETS = json.loads((D.DATA / "template_subset.json").read_text())
SUBSET = _SUBSETS["sequences"]
# test_template uses IAC; these rule sets change the builder, not the figures flown
OTHER_RULES = ("CIVA", "IMAC", "IACGlider", "CIVAGlider")
OTHER_RULES_SUBSET = _SUBSETS["other_rules_sequences"]


def _sequence_id(key: str) -> str:
    return key.split("#")[0].split("@")[0]


def _group(res: D.Result, by) -> dict[str, list[tuple[str, str]]]:
    """key -> [(check, detail)] for the differences of one result."""
    out: dict[str, list[tuple[str, str]]] = {}
    for k in sorted(res.diffs):
        out.setdefault(by(k[1], k[2]), []).append((k[2], res.details[k]))
    return out


@lru_cache
def _corpus_differences(corpus: str) -> tuple[dict, dict]:
    """(figure differences by figure string, sequence differences by sequence id)."""
    logger.disable("pyolan")
    try:
        res = D.differences(corpus)
    finally:
        logger.enable("pyolan")
    figure_checks = set(D.FIGURE_CHECKS)
    fig_res = D.Result(
        diffs={k for k in res.diffs if k[2] in figure_checks}, details=res.details
    )
    seq_res = D.Result(
        diffs={k for k in res.diffs if k[2] in D.SEQUENCE_CHECKS}, details=res.details
    )
    return _group(fig_res, lambda key, check: key), _group(seq_res, lambda key, check: _sequence_id(key))


@lru_cache
def _template_differences(subset: bool, rules: str = "IAC") -> dict:
    ids = (SUBSET if rules == "IAC" else OTHER_RULES_SUBSET) if subset else None
    res = T.differences("library", ids, rules)
    return _group(res, lambda key, check: _sequence_id(key))


def _fail_message(what: str, items: list) -> str:
    return f"{what}: {len(items)} difference(s) from OpenAero\n" + "\n".join(
        f"  {check}: {detail}" for check, detail in items
    )


def _distinct_figures(corpus: str) -> list[str]:
    seen: dict[str, None] = {}
    for seq in D.load_corpus(corpus)["sequences"]:
        for f in seq["figures"]:
            seen.setdefault(f["s"], None)
    return list(seen)


def _pairs(by_corpus) -> list:
    return [pytest.param(c, k, id=f"{c}:{k}") for c in D.CORPORA for k in by_corpus(c)]


@pytest.mark.parametrize("corpus, figure", _pairs(_distinct_figures))
def test_figure(corpus, figure):
    items = _corpus_differences(corpus)[0].get(figure, [])
    assert not items, _fail_message(f"{corpus} figure {figure!r}", items)


@pytest.mark.parametrize(
    "corpus, sequence",
    _pairs(lambda c: [s["id"] for s in D.load_corpus(c)["sequences"]]),
)
def test_sequence(corpus, sequence):
    items = _corpus_differences(corpus)[1].get(sequence, [])
    assert not items, _fail_message(f"{corpus} sequence {sequence}", items)


@pytest.mark.parametrize("sequence", SUBSET)
def test_template(sequence):
    items = _template_differences(True).get(sequence, [])
    assert not items, _fail_message(f"library template {sequence}", items)


@pytest.mark.parametrize(
    "rules, sequence",
    [pytest.param(r, s, id=f"{r}:{s}") for r in OTHER_RULES for s in OTHER_RULES_SUBSET],
)
def test_template_other_rules(rules, sequence):
    """The same exits, and the same expected error, under the other rule sets."""
    items = _template_differences(True, rules).get(sequence, [])
    assert not items, _fail_message(f"library template {sequence} under {rules}", items)


@pytest.mark.parametrize("sequence", [s["id"] for s in D.load_corpus("library")["sequences"]])
def test_template_library_all(sequence):
    """Diagnostic: not in the component lane (about four minutes in all)."""
    items = _template_differences(False).get(sequence, [])
    assert not items, _fail_message(f"library template {sequence}", items)
