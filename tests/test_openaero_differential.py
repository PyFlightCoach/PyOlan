"""PyOlan against OpenAero, figure by figure (plan B1 to B3).

Each corpus in tests/data/openaero/expected holds OpenAero's own trace of every
figure, reduced to the canonical form (tests/openaero/canonical.py). The actual
differences must equal tests/data/openaero/known_differences.json in both
directions: a fix removes its entries, and a new difference fails.

* B1: elements, negative flags, entry and exit attitude, errors, extra figures;
* B2: direction state (direction.py) against OpenAero's entry and exit;
* B3: powered and glider K against OpenAero's sum of base and roll K.

Refresh the expectations with tools/openaero/export.py and propose findings for
new differences with tools/openaero/propose_findings.py.
"""

import sys
from functools import lru_cache
from pathlib import Path

import pytest
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))
from openaero import differential as D  # noqa: E402

pytestmark = pytest.mark.component

B1 = ("elements", "negative", "attitude", "error", "extra")
B2 = ("direction",)
B3 = ("k_powered", "k_glider")
GROUPS = {"elements": B1, "direction": B2, "k": B3}


@lru_cache
def _differences(corpus: str) -> D.Result:
    logger.disable("pyolan")
    try:
        return D.differences(corpus, B1 + B2 + B3)
    finally:
        logger.enable("pyolan")


@pytest.mark.parametrize("group", list(GROUPS))
@pytest.mark.parametrize("corpus", D.CORPORA)
def test_differences_equal_the_known_list(corpus, group):
    checks = GROUPS[group]
    res = _differences(corpus)
    actual = D.Result(
        diffs={k for k in res.diffs if k[2] in checks},
        details=res.details,
        figures=res.figures,
    )
    expected = D.known_set(checks, corpus)
    assert actual.diffs == expected, D.report(actual, expected)


def test_known_differences_name_a_finding_with_a_reason():
    known = D.load_known()
    findings = known["findings"]
    used = set()
    for corpus, checks in known["known"].items():
        assert corpus in D.CORPORA
        for check, by_finding in checks.items():
            assert check in B1 + B2 + B3 + ("template", "template_count"), f"{check} is not a listed check"
            for finding, keys in by_finding.items():
                assert finding in findings and findings[finding].strip(), finding
                assert keys == sorted(set(keys)), f"{corpus}/{check}/{finding} keys not sorted or repeated"
                used.add(finding)
    assert used <= set(findings)


def test_corpora_record_their_provenance():
    sha = (Path(__file__).parents[1] / "tools" / "openaero" / "OPENAERO_SHA").read_text().strip()
    for corpus in D.CORPORA:
        prov = D.load_corpus(corpus)["provenance"]
        assert prov["repository"] == "OpenAero/main"
        assert prov["revision"] == sha
        assert prov["harness_version"]
        assert prov["corpus"] == corpus
        assert D.load_corpus(corpus)["sequences"]
