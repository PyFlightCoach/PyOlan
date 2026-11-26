"""Triage report for the strict OpenAero tests (tests/test_openaero_strict.py).

    python tools/openaero/propose_findings.py [corpus ...] [--templates subset|all]
        [--show N] [--verbose] [--json PATH]

Runs the same comparisons as tests/test_openaero_strict.py, classifies every
current difference with simple rules and prints the counts by finding and by
(corpus, check, finding), the total and samples of the differences no rule fits
("?"). It groups the current failures by finding so that each fix can record
before and after counts (--json writes the counts). The proposals are guesses:
work out the cause of every "?".

The finding IDs and their reasons are in tools/openaero/findings.json; they follow
docs/investigations/olan-openaero-differential-2026-11-25 in the FCScoreFuture
workspace.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE / "tests"))

from loguru import logger  # noqa: E402

from openaero import differential as D  # noqa: E402
import pyolan.direction as direction  # noqa: E402

logger.remove()

# PyOlan's legacy compound codes and non-Aresti figures (primitives.py, second block)
# that are not the figure OpenAero has under the same letters.
F12_BASES = {
    "co", "ico", "tri", "itri", "oj", "ioj", "jw", "dz", "idz", "dvz", "idvz", "dvd",
    "idvd", "rqq", "irqq", "hat", "xm", "xa", "ixa", "vc", "cv", "rcc", "th", "jj",
    "jojo", "jijo", "joji", "joj", "jjoi", "jojio", "oaj", "oajj", "oajjj", "oajjjj",
}
F11_BASES = {"mm", "imm", "oo", "ioo", "ooo", "iooo", "ao", "iao", "rao", "irao", "ro", "iro", "or", "ior"}
F8_BASES = {
    "pp", "ipp", "rpp", "irpp", "qo", "iqo", "hd", "dhd", "kz", "ikz", "vv", "ivv",
    "bh", "ibh", "hp", "iph", "ph", "pbh", "k", "ik", "dq", "idq", "qq", "iqq",
}


def letters(token: str) -> str:
    """The figure letters of a token, without roll letters (f, if, s, is)."""
    body = re.sub(r'"[^"]*"', "", token)
    body = re.sub(r"[^a-zA-Z]", " ", body)
    words = [w for w in body.split() if w not in ("f", "if", "s", "is")]
    word = "".join(words)
    word = re.sub(r"^(if|f|is|s)(?=[a-z])", "", word)
    word = re.sub(r"(?<=[a-z])(if|f|is|s)$", "", word)
    return word


def _paired(text: str, oa_figures: list[dict]) -> dict[int, object]:
    """OpenAero figure index -> PyOlan figure, paired as differential.py does."""
    figs, _ = D.take_all(text)
    out, used = {}, 0
    for f in oa_figures:
        for k in range(used, len(figs)):
            if D._token_matches(figs[k].olan.token, f["s"]):
                out[f["i"]] = figs[k]
                used = k + 1
                break
    return out


def _f1_patched_direction(seq: dict, fig: dict) -> bool:
    """True when the long-forward step (F1) alone fixes this figure's direction."""
    orig = direction.oa_base

    def patched(figure: str):
        f = re.sub(r'"[^"]*"', "", figure)
        f = re.sub(r"-(?=--)", "+", f) if re.fullmatch(r"[-'~]*", f) else re.sub(r"-(?=-)", "+", f)
        return orig(f.replace("+", "~~~"))

    direction.oa_base = patched
    try:
        pf = _paired(seq["text"], seq["figures"]).get(fig["i"])
    finally:
        direction.oa_base = orig
    if pf is None or pf.direction is None or not pf.direction.resolved:
        return False
    d = pf.direction
    return [d.entry_direction, d.entry_attitude, d.exit_direction, d.exit_attitude] == [
        *fig["entry"], *fig["exit"]
    ]


def propose(corpus: str, key: str, check: str, detail: str, figs: dict, seqs: dict) -> str:
    if check in ("k_powered", "k_glider"):
        return "F13"
    if check == "missing":
        token = re.match(r"""^(['"])(.*?)\1 not built""", detail)
        token = token.group(2) if token else ""
        if re.fullmatch(r"[-'`.~+]*", token):
            return "F21"
        if letters(token).lstrip("f") in {"i" + b for b in F12_BASES | {"vv", "hat"}} or letters(token) in F12_BASES:
            return "F12"
        return "?"
    if check == "extra":
        if key.split("@", 1)[1].startswith('"'):
            return "F20"
        return "F19"
    f = figs.get(key)
    if check == "direction":
        sid, idx = key.rsplit("#", 1)
        seq = seqs[sid]
        fig = next(x for x in seq["figures"] if x["i"] == int(idx))
        if fig["aresti"][0].startswith("0."):
            return "F12"
        if _f1_patched_direction(seq, fig):
            return "F1"
        if re.search(r'"[^"]* [^"]*"', seq["text"]):
            return "F20"
        if re.search(r"(^|[^a-z])i?v[^a-z]*\d*i?s", fig["s"]):
            return "F15"
        return "?"
    token = key
    base = letters(token)
    if f is None:
        return "?"
    if f["aresti"][0].startswith("0."):
        return "F12"
    if f["corr"]:
        return "F10"
    if base in F12_BASES:
        return "F12"
    if check == "error":
        return "?"
    if re.search(r"j", base) and any(s[0] == "turn" and s[2] for s in f["c"]):
        return "F17"
    if base in F11_BASES:
        return "F11"
    if check == "negative":
        if re.fullmatch(r"[^a-z]*\d+i?s[^a-z]*", token):
            return "F7"
        return "?"
    if '"' in token:
        return "F20"
    if re.search(r"[;,][^0-9a-z;,]*($|[>^]|[a-eg-hj-rt-z])", token):
        return "F6"
    if re.fullmatch(r"[-+'`.~]*\d+i?s[-+'`.~]*", token):
        return "F7"
    if check == "attitude":
        return "F9"
    if base in F8_BASES or base.lstrip("i") in F8_BASES:
        return "F8"
    if base in ("d", "id", "z", "iz"):
        return "F9"  # 1.1.5 and 1.1.11: a half roll selects the reversing variant
    m = re.search(r"oa (\[.*\]) py (\[.*\])", detail)
    if m:
        oa, py = json.loads(m.group(1)), json.loads(m.group(2))
        if len(oa) == len(py) and all(a[0] == b[0] for a, b in zip(oa, py)):
            rolls_same = all(
                (a[2] if a[0] == "arc" else a[1:]) == (b[2] if b[0] == "arc" else b[1:])
                for a, b in zip(oa, py)
            )
            if rolls_same:
                same_abs = all(
                    a[0] != "arc" or a[1] is None or b[1] is None or abs(a[1]) == abs(b[1])
                    for a, b in zip(oa, py)
                )
                attitude_marked = token.rstrip("~`'.+").endswith("-") or token.lstrip("~`'.+/").startswith("-")
                return "F8" if same_abs else ("F9" if attitude_marked else "?")
    return "?"


TEMPLATE_CHECKS = ("template", "template_count")


def _written_attitudes(token: str) -> tuple[str, str]:
    body = re.sub(r'"[^"]*"', "", token).strip("~`'.+/>^")
    return ("-" if body.startswith("-") else "+", "-" if body.endswith("-") else "+")


def propose_templates(res, entries: dict, seqs: dict) -> dict:
    """Findings for template differences.

    A wrong exit takes the finding of its own cause when it has one: an element,
    attitude or direction difference of the figure, a 90 or 270 degree turn (F4),
    or a written entry attitude that conflicts with the previous figure's written
    exit (F3). Otherwise it is a cascade and takes the cause of the first wrong
    figure before it in the sequence.
    """
    own = {}
    for (corpus, key, check), finding in sorted(entries.items()):
        if corpus == "library" and check in ("elements", "attitude", "direction", "negative"):
            own.setdefault(key, finding)
    out = {}
    by_seq: dict[str, list] = {}
    for k in res.diffs:
        if k[2] == "template":
            sid, idx = k[1].rsplit("#", 1)
            by_seq.setdefault(sid, []).append((int(idx), k))
        else:
            seq = seqs[k[1]]
            detail = res.details[k]
            out[k] = "F5" if "raised" in detail else "F2"
    for sid, items in by_seq.items():
        seq = seqs[sid]
        figs = {f["i"]: f for f in seq["figures"]}
        order = [f["i"] for f in seq["figures"]]
        cascade = None
        count_issue = (("library", sid, "template_count") in res.diffs)
        for idx, k in sorted(items):
            f = figs[idx]
            cause = own.get(f["s"]) or own.get(f"{sid}#{idx}")
            detail = res.details[k]
            heading_wrong = re.search(r"exits (\w+) .*template (\w+)", detail)
            heading_wrong = heading_wrong and heading_wrong.group(1) != heading_wrong.group(2)
            if cause is None and heading_wrong and re.search(r"(^|[^0-9a-z])[13]?j", f["s"]):
                cause = "F4"
            if cause is None:
                pos = order.index(idx)
                if pos > 0:
                    prev = figs[order[pos - 1]]
                    if _written_attitudes(f["s"])[0] != _written_attitudes(prev["s"])[1] and prev["exit"][1] in (0, 180) and f["entry"][1] in (0, 180):
                        cause = "F3"
            if cause is None and cascade is None and count_issue:
                cause = "F2"
            if cause is None:
                cause = cascade or "?"
            if cascade is None:
                cascade = cause
            out[k] = cause
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("corpora", nargs="*", default=list(D.CORPORA))
    ap.add_argument("--show", type=int, default=200, help="print at most N differences")
    ap.add_argument("--verbose", action="store_true", help="print every difference, not only '?'")
    ap.add_argument("--templates", choices=["subset", "all"],
                    help="also compare library templates: the test subset, or all (about four minutes)")
    ap.add_argument("--json", type=Path, help="write the counts to this file")
    args = ap.parse_args()
    entries: dict[tuple[str, str, str], str] = {}
    counts: Counter = Counter()
    shown = 0
    for corpus in args.corpora:
        res = D.differences(corpus)
        data = D.load_corpus(corpus)
        figs = {}
        for s in data["sequences"]:
            for f in s["figures"]:
                figs.setdefault(f["s"], f)
        seqs = {s["id"]: s for s in data["sequences"]}
        for k in sorted(res.diffs):
            finding = propose(*k, res.details[k], figs, seqs)
            counts[(corpus, k[2], finding)] += 1
            if (finding == "?" or args.verbose) and shown < args.show:
                print(finding, k, res.details[k][:300])
                shown += 1
            entries[k] = finding
    if args.templates:
        from openaero import templates as T

        ids = None
        if args.templates == "subset":
            ids = json.loads((D.DATA / "template_subset.json").read_text())["sequences"]
        res = T.differences("library", ids)
        seqs = {s["id"]: s for s in D.load_corpus("library")["sequences"]}
        # a template's own cause is the finding of the library figure or direction
        # difference just proposed above (empty when library was not compared)
        proposals = propose_templates(res, entries, seqs)
        for k in sorted(res.diffs):
            finding = proposals[k]
            counts[("library", k[2], finding)] += 1
            if (finding == "?" or args.verbose) and shown < args.show:
                print(finding, k, res.details[k][:300])
                shown += 1
    by_finding: Counter = Counter()
    for (corpus, check, finding), n in sorted(counts.items()):
        print(f"{corpus:12s} {check:14s} {finding:4s} {n}")
        by_finding[finding] += n
    print()
    for finding, n in sorted(by_finding.items(), key=lambda kv: (kv[0] == "?", kv[0].zfill(4))):
        print(f"{finding:4s} {n}")
    total = sum(by_finding.values())
    print(f"total {total}")
    if args.json:
        args.json.write_text(json.dumps({
            "total": total,
            "by_finding": dict(sorted(by_finding.items())),
            "by_corpus_check_finding": {f"{c}:{k}:{f}": n for (c, k, f), n in sorted(counts.items())},
        }, indent=1) + "\n")


if __name__ == "__main__":
    main()
