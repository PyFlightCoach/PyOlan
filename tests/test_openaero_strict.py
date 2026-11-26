"""PyOlan against OpenAero, one test per item (the ``openaero`` lane).

Each corpus in tests/data/openaero/expected holds OpenAero's own trace of every
figure, reduced to the canonical form (tests/openaero/canonical.py). There is no
list of accepted differences: every difference from OpenAero is a failing test.

* ``test_figure[<corpus>:<figure string>]``: elements, negative flags, entry and
  exit attitude, errors, powered and glider K;
* ``test_sequence[<corpus>:<sequence id>]``: direction state, figures OpenAero
  builds that PyOlan does not (missing) and the reverse (extra);
* ``test_template[<sequence id>]``: parse_olan templates against OpenAero's figure
  exits, for the fixed subset in tests/data/openaero/template_subset.json;
* ``test_template_library_all``: the same for every library sequence (about four
  minutes). It is a diagnostic selection, not part of the openaero lane:

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

TEMPLATE_CHECKS = ("template", "template_count")
SUBSET = json.loads((D.DATA / "template_subset.json").read_text())["sequences"]


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
def _template_differences(subset: bool) -> dict:
    res = T.differences("library", SUBSET if subset else None)
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


@pytest.mark.parametrize("sequence", [s["id"] for s in D.load_corpus("library")["sequences"]])
def test_template_library_all(sequence):
    """Diagnostic: not in the openaero lane (about four minutes in all)."""
    items = _template_differences(False).get(sequence, [])
    assert not items, _fail_message(f"library template {sequence}", items)
