"""Refresh PyOlan's OpenAero expectations from the pinned OpenAero commit.

    python tools/openaero/export.py [all | figures | library | catalogue | syntax | regressions ...]

Run from the PyOlan package directory with the workspace venv. It fetches the
commit in OPENAERO_SHA (fetch_openaero.sh), runs the trace harness (oa-trace.js,
needs node and `npm ci` in this directory) and writes:

* tests/data/openaero/figures.json: the figure catalogue, with provenance;
* tests/data/openaero/sequence_directions.json: entry and exit directions of the
  sequences in tests/data/openaero/regressions.txt marked "[directions]";
* tests/data/openaero/expected/<corpus>.json.gz: the canonical expectation of
  every figure in each corpus (see tests/openaero/canonical.py).

Corpora:

* library: every sequence in OpenAero's data/library.js, rebuilt in Form B.
* catalogue: every catalogue pattern, with empty slots, three seeded fills per
  slot, and class-boundary fills (4, 3, 34 on & slots; spins on $ slots).
* syntax: a fixed set of figures in drawing and notation variations.
* regressions: tests/data/openaero/regressions.txt (add with add_regression.py).
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
DATA = PACKAGE / "tests" / "data" / "openaero"
EXPECTED = DATA / "expected"
REGRESSIONS = DATA / "regressions.txt"
SEED = 1

sys.path.insert(0, str(PACKAGE / "tests"))
from openaero import canonical as C  # noqa: E402


def harness_version() -> str:
    m = re.search(r'HARNESS_VERSION = "([^"]+)"', (HERE / "oa-trace.js").read_text())
    return m.group(1)


def pinned_sha() -> str:
    return (HERE / "OPENAERO_SHA").read_text().strip()


def fetch() -> Path:
    out = subprocess.run(
        [str(HERE / "fetch_openaero.sh")], check=True, capture_output=True, text=True
    ).stdout.strip()
    return Path(out.splitlines()[-1])


REUSE_TRACES = False  # --reuse-traces: canonicalise the last traces again
TRACES = PACKAGE / ".test-artifacts" / "openaero" / "traces"


def trace(oa: Path, *args: str, cache: str | None = None) -> dict:
    """Run the harness. The raw output is kept in TRACES/<cache>.json so that a
    change to canonical.py can be re-applied without running OpenAero again."""
    path = TRACES / f"{cache}.json" if cache else None
    if REUSE_TRACES and path and path.exists():
        return json.loads(path.read_text())
    res = subprocess.run(
        ["node", str(HERE / "oa-trace.js"), str(oa), *args],
        check=True, capture_output=True, text=True, cwd=HERE,
    )
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(res.stdout)
    return json.loads(res.stdout)


def provenance(oa: Path, meta: dict, **extra) -> dict:
    return {
        "repository": "OpenAero/main",
        "revision": pinned_sha(),
        "openaero_version": meta.get("openaero_version"),
        "harness_version": meta.get("harness_version"),
        **extra,
    }


# ---------------------------------------------------------------------------
# corpus generation

FULL = ["1", "22", "2,2", "9", "1f", "1if", "44", "2;2"]
HALF = ["2", "24", "2f", "2if", "6", "1,2", "3,4", "6if", "48"]
QUARTER = ["4", "3", "34", "8", "2,4", "3f", "3if", "5", "7", "5if"]
SPIN = ["1s", "1is", "2s", "5s", "6is", "1s,2", "5is,4"]
CLASSES = {
    "_": FULL,
    "^": HALF,
    "&": FULL + HALF + QUARTER,
    "$": FULL + HALF + QUARTER + SPIN,
    "~": [""],
}
BOUNDARY = {"&": ["4", "3", "34"]}


def _pattern_items(pattern: str) -> tuple[str, list[str], str]:
    """'+_ao(_)_-' -> entry '+', items ['_', 'ao', '(_)', '_'], exit '-'."""
    entry, body, exit_ = pattern[0], pattern[1:-1], pattern[-1]
    items = re.findall(r"\([_^&$~]?\)|[_^&$~]|[a-zA-Z0-9]+", body)
    assert "".join(items) == body, (pattern, items)
    return entry, items, exit_


def pattern_olan(pattern: str, fill) -> str:
    """OLAN for a catalogue pattern, with fill(marker) giving each roll slot."""
    entry, items, exit_ = _pattern_items(pattern)
    out = "-" if entry == "-" else ""
    for it in items:
        if it[0] == "(":
            mark = it[1:-1]
            r = fill(mark) if mark else ""
            out += f"({r})" if r else "()"
        elif it in CLASSES:
            out += fill(it)
        else:
            out += it
    if not re.search(r"\([^)]+\)", out):
        out = out.replace("()", "")
    if exit_ == "-":
        out += "-"
    return out


def catalogue_figures(figures: list[dict], seed: int = SEED) -> list[str]:
    rng = random.Random(seed)
    out: list[str] = []
    seen_patterns: set[str] = set()

    def add(s: str) -> None:
        if s and s not in out:
            out.append(s)

    for f in figures:
        pat = f["pattern"]
        if pat in seen_patterns:
            continue
        seen_patterns.add(pat)
        add(pattern_olan(pat, lambda m: ""))
        for _ in range(3):
            add(pattern_olan(pat, lambda m: rng.choice(CLASSES[m])))
        for boundary in BOUNDARY["&"]:
            if "&" in pat:
                add(pattern_olan(pat, lambda m, b=boundary: b if m == "&" else ""))
        if "$" in pat:
            add(pattern_olan(pat, lambda m: rng.choice(SPIN) if m == "$" else ""))
    return out


def chunk(figures: list[str], n: int = 20) -> list[str]:
    """Sequences of n figures, each starting afresh after the subsequence marker."""
    return [" // ".join(figures[i : i + n]) for i in range(0, len(figures), n)]


# Figures the syntax corpus decorates. They cover lines, loops, hammers, spins,
# turns, rolls in loops and inverted entries; their own geometry is covered by the
# catalogue corpus.
SYNTAX_FIGURES = [
    "o", "2a", "4h4", "iv2s", "1j1", "22", "c,24", "-24ipp8", "p(2)", "1b2",
    "d", "-iv", "3jio15", "2f", "24-", "-1-", "2,24ta3if", "m2", "-o-", "y2",
]


def syntax_sequences(seed: int = SEED) -> list[str]:
    rng = random.Random(seed)
    figs = SYNTAX_FIGURES

    def draw(fig: str) -> str:
        """Drawing characters around and inside the figure."""
        pre = rng.choice(["", "~", "~~", "'", "''", "`", "``", "+", "++"])
        post = rng.choice(["", "~", "~~", ".", "..", "'", "+", "++", "`"])
        body = fig
        letters = re.search(r"[a-zA-Z]+", body)
        if letters and rng.random() < 0.5:
            k = letters.end()
            body = body[:k] + rng.choice([".", "''", "..'", "``"]) + body[k:]
        return pre + body + post

    seqs: list[str] = []
    # drawing characters and line extensions
    for _ in range(6):
        seqs.append(" ".join(draw(f) for f in rng.sample(figs, 6)))
    # entry commands, subsequences, moves, scale, switches, comments, @ labels
    commands = ["ed", "eu", "ej", "eja", "//", "(2,0)", "(-3,1)", "[1,2]", "4%", "3%", "1>", "^", ">", "/"]
    for _ in range(10):
        parts: list[str] = []
        for f in rng.sample(figs, 5):
            if rng.random() < 0.5:
                parts.append(rng.choice(commands))
            if rng.random() < 0.3:
                parts.append(f'"@{rng.choice("ABCDEF")}"')
            parts.append(draw(f))
        seqs.append(" ".join(parts))
    # direction switchers inside figures, comments inside figures
    for f in ["4h4", "1b2", "2,24ta3if", "c,24", "-24ipp8"]:
        seqs.append(f"{f}> o")
        seqs.append(f"{f}^ o")
        seqs.append(f'"a comment" {f} o')
    for f in ["4h4", "p(2)", "c,24"]:
        seqs.append(f'{f[0]}"note"{f[1:]} o')
    # leading separators, empty slots, separators with no roll after them
    seqs += [
        ",24 o", ";24 o", "-,2 o", "-;2- o", ",2f- o",
        "p() o", "o() 2a", "ao() o", "1ao() o",
        "4,h4 o", "4;h4 o", "4h4; o", "4h4, o", "24; o", "2, o", "2;> o",
        "5s, o", "5s; o", "iv2s; o",
    ]
    # attitude markers on roll figures and long-forward lines
    seqs += [
        "24- 1-", "-1- o", "2f- -o", "-.22-- o", "+++2j+++~ o", "~~+iv.s.'++~ o",
        "ed +++2j+++~ ~~+iv.s.'++~ ~.'h.''~", "eu o +++ 2a +", "o - -o",
    ]
    return seqs


def regression_inputs() -> list[tuple[str, bool]]:
    """(sequence, wanted in sequence_directions.json) from regressions.txt."""
    out = []
    for line in REGRESSIONS.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        directions = line.startswith("[directions] ")
        out.append((line.removeprefix("[directions] "), directions))
    return out


# ---------------------------------------------------------------------------
# expectations


def figure_expectation(f: dict) -> dict:
    return {
        "i": f["index"],
        "s": f["string"],
        "aresti": f["aresti"],
        "base": f["base"],
        "kp": f.get("k_powered"),
        "kg": f.get("k_glider"),
        "entry": [f["entryDir"], f["entryAtt"]],
        "exit": [f["exitDir"], f["exitAtt"]],
        "c": C.oa_canonical(f["trace"]),
        "neg": C.oa_negatives(f["trace"]),
        "corr": C.oa_corrections(f["trace"]),
    }


def sequence_expectation(seq: dict, sid: str) -> dict:
    if "error" in seq:
        raise RuntimeError(f"OpenAero failed on {sid}: {seq['error'][:300]}")
    return {
        "id": sid,
        "text": seq["sequence_text"],
        "class": seq.get("sportingClass"),
        "rules": seq.get("rules"),
        "category": seq.get("category"),
        "figures": [figure_expectation(f) for f in seq["figures"] if f.get("trace")],
    }


def write_corpus(name: str, meta: dict, sequences: list[dict], **extra) -> None:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    doc = {"provenance": provenance(None, meta, corpus=name, **extra), "sequences": sequences}
    data = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode()
    # mtime=0 keeps the file identical when nothing changes
    with open(EXPECTED / f"{name}.json.gz", "wb") as fh:
        with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as gz:
            gz.write(data)
    nfig = sum(len(s["figures"]) for s in sequences)
    print(f"{name}: {len(sequences)} sequences, {nfig} figures", file=sys.stderr)


def run_inputs(oa: Path, inputs: list[str], cache: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(inputs) + "\n")
        path = fh.name
    try:
        return trace(oa, "--file", path, cache=cache)
    finally:
        Path(path).unlink()


def export_figures(oa: Path) -> None:
    subprocess.run(
        ["node", str(HERE / "export-figures.js"), str(oa), pinned_sha(),
         harness_version(), str(DATA / "figures.json")],
        check=True, cwd=HERE,
    )


def export_library(oa: Path) -> None:
    res = trace(oa, "--library", cache="library")
    seqs = [sequence_expectation(s, s["name"]) for s in res["sequences"]]
    write_corpus("library", res, seqs, source="data/library.js")


def export_generated(oa: Path, name: str, inputs: list[str], **extra) -> dict:
    res = run_inputs(oa, inputs, name)
    seqs = [
        sequence_expectation(s, f"{name}{k:04d}") for k, s in enumerate(res["sequences"])
    ]
    write_corpus(name, res, seqs, **extra)
    return res


def export_catalogue(oa: Path) -> None:
    figures = json.loads((DATA / "figures.json").read_text())["figures"]
    export_generated(
        oa, "catalogue", chunk(catalogue_figures(figures)), seed=SEED,
        source="data/figures/figures.js",
    )


def export_syntax(oa: Path) -> None:
    export_generated(oa, "syntax", syntax_sequences(), seed=SEED)


def export_regressions(oa: Path) -> None:
    items = regression_inputs()
    res = export_generated(oa, "regressions", [s for s, _ in items], source="regressions.txt")
    directions = []
    for (text, wanted), seq in zip(items, res["sequences"]):
        if not wanted:
            continue
        directions.append({
            "input": text,
            "figures": [
                {
                    "token": f["string"],
                    "entry": {"direction": f["entryDir"], "attitude": f["entryAtt"]},
                    "exit": {"direction": f["exitDir"], "attitude": f["exitAtt"]},
                }
                for f in seq["figures"]
            ],
        })
    (DATA / "sequence_directions.json").write_text(json.dumps({
        "source": provenance(None, res, file="tests/data/openaero/regressions.txt"),
        "sequences": directions,
    }, indent=1) + "\n")
    print(f"sequence_directions: {len(directions)} sequences", file=sys.stderr)


STEPS = {
    "figures": export_figures,
    "library": export_library,
    "catalogue": export_catalogue,
    "syntax": export_syntax,
    "regressions": export_regressions,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="*", default=["all"], choices=["all", *STEPS])
    ap.add_argument("--reuse-traces", action="store_true",
                    help="re-canonicalise the traces of the last run instead of running OpenAero")
    args = ap.parse_args()
    global REUSE_TRACES
    REUSE_TRACES = args.reuse_traces
    what = list(STEPS) if "all" in args.what else args.what
    oa = fetch()
    for name in STEPS:
        if name in what:
            STEPS[name](oa)


if __name__ == "__main__":
    main()
