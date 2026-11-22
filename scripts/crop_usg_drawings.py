"""Crop the USG drawings of every F3A catalogue entry, one image per flying direction.

Usage:
    python -I crop_usg_drawings.py [--drawings DIR] [--out DIR] [GROUP ...]

Reads ``Group_<g>.pdf`` from DRAWINGS (default ``.test-artifacts/usg-drawings``; see
fetch_usg_drawings.py) and writes ``<number>_<slot>.png`` to OUT (default
``.test-artifacts/usg-crops``), the names ``upload_catalogue_images --dir`` expects:

* slot 1 is the right-hand column of the page (label ``J.1``), flown left to right (LTOR);
* slot 2 is the left-hand column (label ``J.1.R``), flown right to left (RTOL).

Each row of a USG page holds two embedded JPEG drawings (about 287 ppi). They are taken from the
PDF unchanged (``pdftohtml -xml`` extracts them and gives their placement) and matched to the
entry whose header text (``pdftotext -bbox-layout``) sits at the top of the row. The images are
trimmed of white margin and saved as greyscale PNG. Entries with no image in one column are
reported. The drawings are Roland Poidevin's (c) 2023: the crops are for upload with credit
and are not to be committed. Needs poppler (pdftohtml, pdftotext) and Pillow.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

GROUPS = [f"{n:02d}" for n in range(1, 31)] + list("ACDEFGHJKLMNPQ")
MIN_SIDE = 150  # px: smaller embedded images are logos, not drawings
ROW_SLACK = 8  # points a row's header may sit above the top of its drawing
WHITE = 235  # pixels at or above this grey level are margin
MARGIN = 4  # px kept around the trimmed drawing
SLOT_LTOR, SLOT_RTOL = 1, 2
ZOOM = 2  # pdftohtml scales every coordinate by this


@dataclass(frozen=True)
class Placed:
    """An embedded image: page (1-based), placement in points and the extracted file."""

    page: int
    left: float
    top: float
    width: float
    height: float
    path: Path


def number_key(label: str) -> str:
    """A header label such as ``j.1``, ``1.9`` or ``01.9`` as the catalogue number ``J.1``/``01.9``."""
    group, item = label.split(".")
    return f"{int(group):02d}.{int(item)}" if group.isdigit() else f"{group.upper()}.{int(item)}"


def entry_rows(bbox_text: str) -> dict[str, tuple[int, float]]:
    """Catalogue number -> (page, header y in points) from ``pdftotext -bbox-layout`` output."""
    rows: dict[str, tuple[int, float]] = {}
    page = 0
    for line in bbox_text.splitlines():
        if "<page " in line:
            page += 1
        m = re.search(r'yMin="([\d.]+)".*>([0-9A-Za-z]{1,2}\.\d{1,2})</word>', line)
        if m:
            rows.setdefault(number_key(m.group(2)), (page, float(m.group(1))))
    return rows


def slot_of(image: Placed, page_width: float) -> int:
    """Right-hand column is flown left to right (slot 1), left-hand column right to left (slot 2)."""
    return SLOT_LTOR if image.left + image.width / 2 > page_width / 2 else SLOT_RTOL


def match_rows(rows: dict[str, tuple[int, float]], images: list[Placed], page_width: float):
    """(number, slot) -> image. An image belongs to the entry on its page whose header lies
    from ROW_SLACK points above the image's top to its bottom, the nearest to the top if several."""
    found: dict[tuple[str, int], Placed] = {}
    for image in images:
        candidates = [
            (abs(y - image.top), number)
            for number, (page, y) in rows.items()
            if page == image.page and image.top - ROW_SLACK <= y <= image.top + image.height
        ]
        if candidates:
            found.setdefault((min(candidates)[1], slot_of(image, page_width)), image)
    return found


def trim(im: Image.Image) -> Image.Image:
    """Greyscale, cropped to the non-white content with a small margin."""
    im = im.convert("L")
    ys, xs = np.where(np.asarray(im) < WHITE)
    if not len(xs):
        return im
    return im.crop((max(0, xs.min() - MARGIN), max(0, ys.min() - MARGIN),
                    min(im.width, xs.max() + MARGIN + 1), min(im.height, ys.max() + MARGIN + 1)))


def crop_name(number: str, slot: int) -> str:
    return f"{number}_{slot}.png"


def placed_images(pdf: Path, work: Path) -> tuple[list[Placed], float]:
    """Extract the drawings of a PDF into ``work`` and read their placement."""
    subprocess.run(["pdftohtml", "-xml", "-zoom", str(ZOOM), str(pdf), str(work / "p")],
                   check=True, capture_output=True)
    root = ET.parse(work / "p.xml").getroot()
    images, width = [], 595.28
    for page in root.iter("page"):
        width = float(page.get("width")) / ZOOM
        for el in page.iter("image"):
            images.append(Placed(int(page.get("number")), *(float(el.get(k)) / ZOOM for k in ("left", "top", "width", "height")),
                                 work / el.get("src")))
    return images, width


def crop_group(pdf: Path, out_dir: Path) -> tuple[list[str], list[tuple[str, int]]]:
    """Write the crops of one group's PDF. Returns (numbers found, [(number, missing slot)])."""
    bbox = subprocess.run(["pdftotext", "-bbox-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    rows = entry_rows(bbox)
    with tempfile.TemporaryDirectory() as tmp:
        images, width = placed_images(pdf, Path(tmp))
        images = [i for i in images if min(Image.open(i.path).size) >= MIN_SIDE]
        found = match_rows(rows, images, width)
        for (number, slot), image in found.items():
            trim(Image.open(image.path)).save(out_dir / crop_name(number, slot), optimize=True)
    missing = [(n, s) for n in rows for s in (SLOT_LTOR, SLOT_RTOL) if (n, s) not in found]
    return list(rows), missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("groups", nargs="*", help="groups to crop (default all)")
    parser.add_argument("--drawings", type=Path, default=Path(".test-artifacts/usg-drawings"))
    parser.add_argument("--out", type=Path, default=Path(".test-artifacts/usg-crops"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    groups = [g.upper() if g.isalpha() else f"{int(g):02d}" for g in args.groups] or GROUPS
    total, missing = 0, []
    for group in groups:
        pdf = args.drawings / f"Group_{group}.pdf"
        if not pdf.exists():
            print(f"group {group}: {pdf} not found", file=sys.stderr)
            continue
        numbers, gaps = crop_group(pdf, args.out)
        total += len(numbers)
        missing += gaps
        print(f"group {group}: {len(numbers)} entries, {len(gaps)} missing")
    print(f"{total} entries; {len(missing)} missing drawings")
    for number, slot in missing:
        print(f"missing: {number} slot {slot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
