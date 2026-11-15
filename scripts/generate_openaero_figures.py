"""Extract OpenAero's figure drawing table for the direction port.

Usage: python scripts/generate_openaero_figures.py /path/to/OpenAero/data/figures/figures.js

Writes src/pyolan/data/openaero_figures.json mapping each OpenAero figure base
(as OpenAero's figBaseLookup keys it, e.g. "+b+") to the ordered list of
[pattern, draw] pairs. The order is the file order, which OpenAero uses to
break ties when it picks the figure variant that best fits the rolls.
Mirrors js/main/04-complex-shapes.js (figure parsing, around line 4060).
"""

import json
import re
import sys
from pathlib import Path

TURN = re.compile(r"[0-9\+\-]j[io0-9\+\-]")  # regexTurn
TURNS_AND_ROLLS = re.compile(r"[\d\(\)\^_&$~]+")  # regexTurnsAndRolls


def main(path: str) -> None:
    text = Path(path).read_text(encoding="utf-8-sig")
    table: dict[str, list[list[str]]] = {}
    for line in text.splitlines():
        m = re.match(r'\s*"([^"]+)",?\s*$', line)
        if not m:
            continue
        parts = " ".join(m.group(1).split()).split(" ")
        if len(parts) < 3 or re.match(r"F\d", m.group(1)):
            continue
        pattern, _aresti, draw = parts[0], parts[1], parts[2]
        base = pattern if TURN.search(pattern) else TURNS_AND_ROLLS.sub("", pattern)
        table.setdefault(base, []).append([pattern, draw])
    out = Path(__file__).parents[1] / "src/pyolan/data/openaero_figures.json"
    out.write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(table)} bases, {sum(map(len, table.values()))} figures -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
