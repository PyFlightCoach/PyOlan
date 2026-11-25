"""parse_olan templates against OpenAero's figure exits (plan B4).

test_template_subset runs in the component lane on SUBSET, a fixed set of library
sequences chosen to cover every finding that reaches the templates, every rule
set and both classes. test_template_library compares every library sequence
(about four minutes); it is a diagnostic selection:

    .venv/bin/python scripts/test.py diagnostic --package PyOlan \\
        --select packages/PyOlan/tests/test_openaero_templates.py::test_template_library

Differences are listed in tests/data/openaero/known_differences.json under the
checks "template" and "template_count" (see tests/openaero/templates.py).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from openaero import differential as D  # noqa: E402
from openaero import templates as T  # noqa: E402

pytestmark = pytest.mark.component

CHECKS = ("template", "template_count")
SUBSET = json.loads((D.DATA / "template_subset.json").read_text())["sequences"]


def _known(ids: list[str] | None) -> set:
    known = D.known_set(CHECKS, "library")
    if ids is None:
        return known
    return {k for k in known if k[1].split("#")[0] in ids}


def test_template_subset():
    res = T.differences("library", SUBSET)
    expected = _known(SUBSET)
    assert res.diffs == expected, D.report(res, expected)


def test_template_library():
    res = T.differences("library")
    expected = _known(None)
    assert res.diffs == expected, D.report(res, expected)
