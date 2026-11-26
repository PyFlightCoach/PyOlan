"""Differences between PyOlan and the OpenAero expectations.

The expectations are the gzipped corpora in tests/data/openaero/expected, written by
tools/openaero/export.py. Each difference is a (corpus, key, check) triple:

* figure checks, keyed by the figure string as OpenAero has it:
  - ``elements``: the canonical form (canonical.py) differs;
  - ``negative``: the negative flags of snaps and spins differ;
  - ``attitude``: the entry or exit attitude (upright or inverted) differs;
  - ``k_powered`` / ``k_glider``: K differs, or PyOlan cannot compute it;
  - ``error``: PyOlan raises while building the figure's elements;
* sequence checks, keyed by ``<sequence id>#<figure index>``:
  - ``direction``: PyOlan's direction state (direction.py) differs from OpenAero's
    entry or exit direction and attitude;
  - ``missing``: OpenAero builds a figure that PyOlan does not (B5 covers these);
  - ``extra``: PyOlan builds a figure that OpenAero does not
    (key ``<sequence id>@<token>``).

There is no list of expected differences: every difference is a failing test in
the ``openaero`` lane (tests/test_openaero_strict.py). tools/openaero/propose_findings.py
groups the current differences by finding (tools/openaero/findings.json).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pyolan.direction import DirectionState
from pyolan.drawing import olan_items
from pyolan.errors import NoFigureLeft, OlanParseError
from pyolan.figure_parser import OlanFig
import schemas.positioning as p

from . import canonical as C

DATA = Path(__file__).resolve().parents[1] / "data" / "openaero"
EXPECTED = DATA / "expected"
CORPORA = ("library", "catalogue", "syntax", "regressions")
FIGURE_CHECKS = ("elements", "negative", "attitude", "k_powered", "k_glider", "error")
SEQUENCE_CHECKS = ("direction", "missing", "extra")


@lru_cache
def load_corpus(name: str) -> dict:
    with gzip.open(EXPECTED / f"{name}.json.gz", "rt") as fh:
        return json.load(fh)


@dataclass
class PyFigure:
    olan: OlanFig
    direction: object | None
    direction_error: str | None = None


def take_all(text: str) -> tuple[list[PyFigure], str | None]:
    """Read every figure the way parse_olan does: OlanFig.take, then the
    direction state. An item that raises OlanParseError is skipped. Returns the
    figures and the errors."""
    data = olan_items(text)
    state = DirectionState()
    out: list[PyFigure] = []
    errors = []
    while data:
        try:
            ofig, data = OlanFig.take(data)
        except NoFigureLeft:
            break
        except OlanParseError as e:
            # parse_olan raises here; skip the item so the rest is still compared
            errors.append(f"OlanParseError: {e}")
            data = data[e.index + 1:]
            continue
        try:
            out.append(PyFigure(ofig, state.apply(ofig)))
        except Exception as e:  # noqa: BLE001
            out.append(PyFigure(ofig, None, f"{type(e).__name__}: {e}"))
    return out, "; ".join(errors) or None


def _token_matches(py_token: str, oa_string: str) -> bool:
    """OpenAero's figure string is the token, less a leading move-forward (">")."""
    token = py_token.lstrip(">")
    return oa_string in (py_token, token, token.replace("_", ""))


@dataclass
class Result:
    diffs: set[tuple[str, str, str]] = field(default_factory=set)
    details: dict[tuple[str, str, str], str] = field(default_factory=dict)
    figures: int = 0

    def add(self, corpus: str, key: str, check: str, detail: str) -> None:
        k = (corpus, key, check)
        self.diffs.add(k)
        self.details.setdefault(k, detail)


def _k(ofig: OlanFig, glider: bool) -> int | str:
    try:
        return ofig.k_factor(glider=glider)
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}"


def compare_figure(res: Result, corpus: str, f: dict, ofig: OlanFig, checks: set[str]) -> None:
    key = f["s"]
    if "elements" in checks or "error" in checks:
        try:
            py_c = C.py_canonical(ofig.create_elements())
        except Exception as e:  # noqa: BLE001
            res.add(corpus, key, "error", f"{type(e).__name__}: {str(e)[:120]}")
            py_c = None
        if py_c is not None and not C.segments_equal(f["c"], py_c):
            res.add(corpus, key, "elements", f"oa {json.dumps(f['c'])} py {json.dumps(py_c)}")
    if "negative" in checks:
        py_n = C.py_negatives(ofig)
        if py_n != f["neg"]:
            res.add(corpus, key, "negative", f"oa {f['neg']} py {py_n}")
    if "attitude" in checks:
        issues = []
        for name, oa_att, py_att in (("entry", f["entry"][1], ofig.entry), ("exit", f["exit"][1], ofig.exit)):
            if oa_att in (0, 180) and (oa_att == 180) != (py_att == p.Orientation.INVERTED):
                issues.append(f"{name} oa {oa_att} py {py_att.name}")
        if issues:
            res.add(corpus, key, "attitude", "; ".join(issues))
    for check, glider, oa_k in (("k_powered", False, f["kp"]), ("k_glider", True, f["kg"])):
        if check in checks and oa_k is not None:
            py_k = _k(ofig, glider)
            if py_k != sum(oa_k):
                res.add(corpus, key, check, f"oa {sum(oa_k)} {f['aresti']} {oa_k} py {py_k}")


def compare_sequence(res: Result, corpus: str, seq: dict, checks: set[str]) -> None:
    py_figs, stop = take_all(seq["text"])
    used = 0
    for f in seq["figures"]:
        res.figures += 1
        match = None
        for k in range(used, len(py_figs)):
            if _token_matches(py_figs[k].olan.token, f["s"]):
                match = k
                break
        skey = f"{seq['id']}#{f['i']}"
        if match is None:
            if "missing" in checks:
                res.add(corpus, skey, "missing", f"{f['s']!r} not built by PyOlan" + (f" (stopped: {stop})" if stop else ""))
            continue
        if "extra" in checks:
            for k in range(used, match):
                res.add(corpus, f"{seq['id']}@{py_figs[k].olan.token}", "extra", "PyOlan builds a figure OpenAero does not")
        used = match + 1
        pf = py_figs[match]
        compare_figure(res, corpus, f, pf.olan, checks)
        if "direction" in checks:
            d = pf.direction
            if d is None:
                res.add(corpus, skey, "direction", f"{f['s']!r}: {pf.direction_error}")
            elif d.resolved:
                py = [d.entry_direction, d.entry_attitude, d.exit_direction, d.exit_attitude]
                oa = [*f["entry"], *f["exit"]]
                if py != oa:
                    res.add(corpus, skey, "direction", f"{f['s']!r}: oa {oa} py {py}")
            else:
                res.add(corpus, skey, "direction", f"{f['s']!r}: PyOlan has no OpenAero base")
    if "extra" in checks:
        for k in range(used, len(py_figs)):
            res.add(corpus, f"{seq['id']}@{py_figs[k].olan.token}", "extra", "PyOlan builds a figure OpenAero does not")


def differences(corpus: str, checks: tuple[str, ...] = FIGURE_CHECKS + SEQUENCE_CHECKS) -> Result:
    res = Result()
    check_set = set(checks)
    for seq in load_corpus(corpus)["sequences"]:
        compare_sequence(res, corpus, seq, check_set)
    return res
