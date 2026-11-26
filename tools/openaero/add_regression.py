"""Add an OLAN sequence to the regressions corpus and refresh its expectations.

    python tools/openaero/add_regression.py 'OLAN sequence' [--comment 'where it came from'] [--directions]

Appends the sequence to tests/data/openaero/regressions.txt and re-exports the
regressions corpus (and sequence_directions.json) from the pinned OpenAero
commit. Run the PyOlan component lane afterwards: there is no list of accepted
differences, so a new difference is a failing test until it is fixed.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("olan")
    ap.add_argument("--comment", default="")
    ap.add_argument("--directions", action="store_true", help="also check it in test_direction.py")
    args = ap.parse_args()
    olan = " ".join(args.olan.split())
    if not olan:
        raise SystemExit("empty sequence")
    existing = [s for s, _ in export.regression_inputs()]
    if olan in existing:
        raise SystemExit("already in regressions.txt")
    lines = ["", f"# {args.comment}"] if args.comment else []
    lines.append(("[directions] " if args.directions else "") + olan)
    with export.REGRESSIONS.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    export.export_regressions(export.fetch())


if __name__ == "__main__":
    main()
