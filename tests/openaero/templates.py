"""parse_olan templates against OpenAero's figure exits (plan B4).

For each figure that OpenAero exits level, the template's exit heading and its
attitude (upright or inverted, from the body z axis) are compared with OpenAero's
physical exit, as the server builds templates: parse_olan with a rule set's builder
(IAC unless another is given; category unlimited) and the wind from the right (RTOL).
Differences:

* ``template``, key ``<sequence id>#<figure index>``: the exit differs, or the
  template does not exit level where OpenAero does;
* ``template_count``, key ``<sequence id>``: parse_olan builds a different number
  of figures, or raises (detail);
* ``heading_override``, key ``<sequence id>``: parse_olan warned that a template left
  the box the other way and that it restarted on OpenAero's heading.

A sequence whose figures do not link (a figure written to start in the other
attitude from the one the figure before ends in, which OpenAero autocorrects) is
an expected error instead (D2): parse_olan must raise OlanParseError at that figure,
and its exits are not compared. The join is found from OpenAero's own trace.

A sequence with one of OpenAero's non-Aresti figures (Family 0, catalogue number 0.x,
the point tip among them) is an expected error too (Phase S, SQ5): parse_olan must
raise OlanParseError with the non-Aresti detail at the first such figure, unless a
figure before it fails to link, and its exits are not compared.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

import geometry as g
import numpy as np
import schemas.positioning as p
from loguru import logger

from pyolan.direction import FigureDirection, physical_to_heading
from pyolan.errors import OlanParseError
from pyolan.figure_parser import NON_ARESTI, non_aresti
from pyolan.parser import HEADING_OVERRIDE, parse_olan

from . import differential as D

WIND = p.Heading.RTOL


@lru_cache
def builder(rules: str = "IAC"):
    from tuning.builders import load_builder

    return load_builder(rules, category="unlimited")


def template_exit(tp) -> tuple[p.Heading, bool]:
    heading = p.Heading.infer(tp.att.bearing()[-1])
    # body z points down when upright (world z up)
    zb = tp.att[-1].transform_point(g.PZ(1))
    return heading, float(zb.z[0]) > 0


def exit_pitch(tp) -> float:
    """The template's pitch at the exit, degrees (body x against the horizontal)."""
    xb = tp.att[-1].transform_point(g.PX(1))
    return float(np.degrees(np.arcsin(np.clip(xb.z[0], -1, 1))))


_RESTARTS = ("//", "eu", "ed", "ej", "eja")


def unlinked_join(seq: dict) -> dict | None:
    """The first OpenAero figure whose entry attitude OpenAero autocorrected: it
    enters upright or inverted, the figure before it exits in the other one, and
    no subsequence ("//") or entry command (eu, ed, ej, eja) lies between them."""
    items = seq["text"].split()
    figures = seq["figures"]
    for prev, f in zip(figures, figures[1:]):
        between = items[prev["i"] + 1 : f["i"]]
        if any(item in _RESTARTS for item in between):
            continue
        before, after = prev["exit"][1], f["entry"][1]
        if before in (0, 180) and after in (0, 180) and before != after:
            return f
    return None


def first_non_aresti(seq: dict) -> dict | None:
    """The first figure OpenAero builds that is one of its non-Aresti figures."""
    return next((f for f in seq["figures"] if non_aresti(f["aresti"])), None)


@contextmanager
def heading_overrides():
    """The heading override warnings parse_olan logs inside the block."""
    messages: list[str] = []
    sink = logger.add(
        lambda m: messages.append(m.record["message"]),
        level="WARNING",
        filter=lambda record: HEADING_OVERRIDE in record["message"],
    )
    try:
        yield messages
    finally:
        logger.remove(sink)


def compare_sequence(res: D.Result, corpus: str, seq: dict, rules: str = "IAC") -> None:
    oa = seq["figures"]
    join = unlinked_join(seq)
    family_0 = first_non_aresti(seq)
    if family_0 is not None and (join is None or family_0["i"] <= join["i"]):
        # parse_olan reads the figures in order: it stops at the first non-Aresti
        # figure, which comes before any figure that does not link
        try:
            with heading_overrides():
                parse_olan(seq["text"], builder(rules), WIND)
        except OlanParseError as e:
            if e.detail != NON_ARESTI or not D._token_matches(e.token or "", family_0["s"]):
                res.add(corpus, seq["id"], "template_count",
                        f"expected the non-Aresti error at {family_0['s']!r}, parse_olan raised: {str(e)[:160]}")
        except Exception as e:  # noqa: BLE001
            res.add(corpus, seq["id"], "template_count", f"parse_olan raised {type(e).__name__}: {str(e)[:120]}")
        else:
            res.add(corpus, seq["id"], "template_count",
                    f"figure {family_0['s']!r} is non-Aresti; parse_olan must raise (SQ5)")
        return
    try:
        with heading_overrides() as overrides:
            figs = parse_olan(seq["text"], builder(rules), WIND)
    except OlanParseError as e:
        if join is None or not D._token_matches(e.token or "", join["s"]) or "ends" not in e.detail:
            where = "" if join is None else f" (expected the D2 error at {join['s']!r})"
            res.add(corpus, seq["id"], "template_count", f"parse_olan raised OlanParseError: {str(e)[:160]}{where}")
        return
    except Exception as e:  # noqa: BLE001
        res.add(corpus, seq["id"], "template_count", f"parse_olan raised {type(e).__name__}: {str(e)[:120]}")
        return
    if overrides:
        res.add(corpus, seq["id"], "heading_override", "; ".join(overrides))
    if join is not None:
        res.add(
            corpus, seq["id"], "template_count",
            f"figure {join['s']!r} does not link to the figure before it; parse_olan must raise (D2)",
        )
        return
    if len(figs) != len(oa):
        res.add(corpus, seq["id"], "template_count", f"{len(figs)} templates, OpenAero {len(oa)} figures")
    k = 0
    for f in figs:
        while k < len(oa) and not D._token_matches(f.olan.token, oa[k]["s"]):
            k += 1
        if k >= len(oa):
            break
        o = oa[k]
        k += 1
        res.figures += 1
        exit_dir, exit_att = o["exit"]
        if exit_att not in (0, 180):
            continue
        want = (physical_to_heading(FigureDirection._physical(exit_dir, exit_att), WIND), exit_att == 180)
        got = template_exit(f.template)
        pitch = exit_pitch(f.template)
        if abs(pitch) > 10:
            # a heading means nothing for a vertical exit, and the next figure
            # would start from it
            res.add(
                corpus, f"{seq['id']}#{o['i']}", "template",
                f"{o['s']!r}: OpenAero exits level, template pitch {pitch:.0f} degrees",
            )
        elif got != want:
            res.add(
                corpus, f"{seq['id']}#{o['i']}", "template",
                f"{o['s']!r}: OpenAero exits {want[0].name} {'inverted' if want[1] else 'upright'}, "
                f"template {got[0].name} {'inverted' if got[1] else 'upright'}",
            )


def differences(corpus: str, ids: list[str] | None = None, rules: str = "IAC") -> D.Result:
    res = D.Result()
    for seq in D.load_corpus(corpus)["sequences"]:
        if ids is None or seq["id"] in ids:
            compare_sequence(res, corpus, seq, rules)
    return res
