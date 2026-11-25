"""parse_olan templates against OpenAero's figure exits (plan B4).

For each figure that OpenAero exits level, the template's exit heading and its
attitude (upright or inverted, from the body z axis) are compared with OpenAero's
physical exit, as the server builds templates: parse_olan with the IAC builder
(category unlimited) and the wind from the right (RTOL). Differences:

* ``template``, key ``<sequence id>#<figure index>``: the exit differs;
* ``template_count``, key ``<sequence id>``: parse_olan builds a different number
  of figures, or raises (detail).
"""

from __future__ import annotations

from functools import lru_cache

import geometry as g
import schemas.positioning as p
from loguru import logger

from pyolan.direction import FigureDirection, physical_to_heading
from pyolan.parser import parse_olan

from . import differential as D

WIND = p.Heading.RTOL


@lru_cache
def builder():
    from tuning.builders import load_builder

    return load_builder("IAC", category="unlimited")


def template_exit(tp) -> tuple[p.Heading, bool]:
    heading = p.Heading.infer(tp.att.bearing()[-1])
    # body z points down when upright (world z up)
    zb = tp.att[-1].transform_point(g.PZ(1))
    return heading, float(zb.z[0]) > 0


def compare_sequence(res: D.Result, corpus: str, seq: dict) -> None:
    oa = seq["figures"]
    logger.disable("pyolan")
    try:
        figs = parse_olan(seq["text"], builder(), WIND)
    except Exception as e:  # noqa: BLE001
        res.add(corpus, seq["id"], "template_count", f"parse_olan raised {type(e).__name__}: {str(e)[:120]}")
        return
    finally:
        logger.enable("pyolan")
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
        if got != want:
            res.add(
                corpus, f"{seq['id']}#{o['i']}", "template",
                f"{o['s']!r}: OpenAero exits {want[0].name} {'inverted' if want[1] else 'upright'}, "
                f"template {got[0].name} {'inverted' if got[1] else 'upright'}",
            )


def differences(corpus: str, ids: list[str] | None = None) -> D.Result:
    res = D.Result()
    for seq in D.load_corpus(corpus)["sequences"]:
        if ids is None or seq["id"] in ids:
            compare_sequence(res, corpus, seq)
    return res
