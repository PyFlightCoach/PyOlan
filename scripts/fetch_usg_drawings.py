"""Download the FAI USG drawing PDFs for local review.

Usage:
    python -I fetch_usg_drawings.py [OUT_DIR] [GROUP ...]

Writes ``Group_<g>.pdf`` (the names scrape_usg_drawings.py reads) into OUT_DIR,
by default ``.test-artifacts/usg-drawings`` under the current directory. With no
groups, all 44 are fetched; files already there are kept. The drawings are
Roland Poidevin's (c) 2023: they are for local comparison and are not to be
committed (``.test-artifacts`` is untracked).
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

URL = "https://usg.f3a.fr/Drawings/Group:{group}_Aresti.pdf"
GROUPS = [f"{n:02d}" for n in range(1, 31)] + list("ACDEFGHJKLMNPQ")


def remote_name(group: str) -> str:
    """The site uses a lower case letter for the lettered groups."""
    return group.lower() if group.isalpha() else group


def fetch(group: str, out_dir: Path) -> Path:
    target = out_dir / f"Group_{group}.pdf"
    if target.exists():
        return target
    with urllib.request.urlopen(URL.format(group=remote_name(group)), timeout=60) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"group {group}: not a PDF")
    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else Path(".test-artifacts/usg-drawings")
    groups = [g.upper() if g.isalpha() else f"{int(g):02d}" for g in argv[1:]] or GROUPS
    for group in groups:
        print(fetch(group, out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
