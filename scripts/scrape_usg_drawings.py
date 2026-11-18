"""Scrape FAI F3A Unknown Schedule Generator drawing PDFs into a JSON fixture.

Usage:
    python -I scrape_usg_drawings.py PDF_DIR OUTPUT_JSON

PDF_DIR holds the downloaded ``Group_<g>.pdf`` files (one per USG group). The
text layer is read with ``pdftotext -layout``. Unknown line labels, unknown
manoeuvre kinds and malformed entries raise an error rather than being guessed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HEADER_RE = re.compile(r"^\s*([0-9]{2}|[A-Za-z])\.(\d{1,2})\s+-\s+(\S.*?)\s*$")
KIND_RE = re.compile(r"^\s*(Central|Turnaround)\s+Manoeuver\s+K=(\d+)\s*$")
ATTITUDE_RE = re.compile(r"^\s*Attitude\s*:\s*(\w+)->(\w+)\s*$")
HEIGHT_RE = re.compile(r"^\s*Height\s*:\s*(\w+)->(\w+)\s*$")
LABEL_RE = re.compile(r"^\s*[A-Za-z][A-Za-z ]*\s*:")
FOOTER_RES = (
    re.compile(r"^\s*Unknown Schedule Generator\s*(-.*)?$"),
    re.compile(r"^\s*Group\s*:\s*\S+\s*$"),
)
GROUP_ORDER = [f"{n:02d}" for n in range(1, 31)] + list("ACDEFGHJKLMNPQ")


def pdf_text(path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def is_footer(line: str) -> bool:
    return any(rx.match(line) for rx in FOOTER_RES)


def parse_text(text: str, group: str) -> list[dict]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    entries: list[dict] = []
    current: dict | None = None
    desc_parts: list[str] = []
    stage = "none"  # none -> description -> kind -> attitude -> height

    def finish(entry: dict) -> None:
        missing = [k for k in ("kind", "k", "entry_attitude", "entry_height") if k not in entry]
        if missing:
            raise ValueError(f"{entry['number']}: missing {missing}")
        entries.append(entry)

    for raw in lines:
        line = raw.strip()
        if not line or is_footer(raw):
            continue
        m = HEADER_RE.match(raw)
        if m:
            if current is not None and stage != "height":
                raise ValueError(f"entry {current['number']} incomplete at stage {stage}")
            if current is not None:
                finish(current)
            letter_or_num, sub = m.group(1), int(m.group(2))
            prefix = letter_or_num.upper()
            if prefix != group and prefix.lstrip("0") != group.lstrip("0"):
                raise ValueError(f"entry {prefix}.{sub} found in group {group}")
            number = f"{prefix}.{sub}"
            current = {"number": number, "group": group}
            desc_parts = [m.group(3)]
            stage = "description"
            continue
        if current is None:
            # Page titles and other text before the first entry of a group.
            continue
        km = KIND_RE.match(raw)
        if km:
            if stage != "description":
                raise ValueError(f"{current['number']}: kind line out of order")
            current["description"] = " ".join(desc_parts)
            current["k"] = int(km.group(2))
            current["kind"] = "centre" if km.group(1) == "Central" else "turnaround"
            stage = "kind"
            continue
        am = ATTITUDE_RE.match(raw)
        if am:
            if stage != "kind":
                raise ValueError(f"{current['number']}: attitude line out of order")
            current["entry_attitude"], current["exit_attitude"] = am.group(1), am.group(2)
            stage = "attitude"
            continue
        hm = HEIGHT_RE.match(raw)
        if hm:
            if stage != "attitude":
                raise ValueError(f"{current['number']}: height line out of order")
            current["entry_height"], current["exit_height"] = hm.group(1), hm.group(2)
            stage = "height"
            continue
        if LABEL_RE.match(raw):
            raise ValueError(f"{current['number']}: unknown field line {line!r}")
        if stage == "description":
            desc_parts.append(line)
        elif stage == "height":
            # Free text after a complete entry (notes such as "N.B. ...") is not part of it.
            continue
        else:
            raise ValueError(f"{current['number']}: unexpected line {line!r} at {stage}")

    if current is not None:
        if stage != "height":
            raise ValueError(f"entry {current['number']} incomplete at stage {stage}")
        finish(current)
    return entries


def sort_key(item: dict) -> tuple:
    group = item["group"]
    return (GROUP_ORDER.index(group), int(item["number"].split(".")[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    entries: list[dict] = []
    for group in GROUP_ORDER:
        pdf = args.pdf_dir / f"Group_{group}.pdf"
        if not pdf.is_file():
            raise SystemExit(f"missing {pdf}")
        group_entries = parse_text(pdf_text(pdf), group)
        if not group_entries:
            raise SystemExit(f"no entries parsed from {pdf}")
        entries.extend(group_entries)

    numbers = [e["number"] for e in entries]
    if len(set(numbers)) != len(numbers):
        raise SystemExit("duplicate manoeuvre numbers")

    entries.sort(key=sort_key)
    ordered = []
    for e in entries:
        ordered.append(
            {
                "number": e["number"],
                "group": e["group"],
                "description": e["description"],
                "k": e["k"],
                "kind": e["kind"],
                "entry_attitude": e["entry_attitude"],
                "exit_attitude": e["exit_attitude"],
                "entry_height": e["entry_height"],
                "exit_height": e["exit_height"],
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(ordered, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(ordered)} entries to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
