"""The OpenAero expectations record where they came from.

The comparisons themselves are the strict tests in test_openaero_strict.py
(the ``openaero`` lane).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from openaero import differential as D  # noqa: E402

pytestmark = pytest.mark.component


def test_corpora_record_their_provenance():
    sha = (Path(__file__).parents[1] / "tools" / "openaero" / "OPENAERO_SHA").read_text().strip()
    for corpus in D.CORPORA:
        prov = D.load_corpus(corpus)["provenance"]
        assert prov["repository"] == "OpenAero/main"
        assert prov["revision"] == sha
        assert prov["harness_version"]
        assert prov["corpus"] == corpus
        assert D.load_corpus(corpus)["sequences"]
