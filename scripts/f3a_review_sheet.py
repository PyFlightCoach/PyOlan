"""Review sheets: the USG drawing of each F3A catalogue entry beside our template.

Usage (from the repository root, with the workspace environment):
    .venv/bin/python packages/PyOlan/scripts/f3a_review_sheet.py GROUP [GROUP ...]
        [--drawings DIR] [--out DIR]

For each group one PNG is written to OUT_DIR (default ``.test-artifacts/f3a-review``):
for every catalogue entry, the drawing (the left-hand column of the USG page,
which flies right to left as our templates do) next to the f3a builder's
template of the parsed figure. In the template rolls are red, loops blue and
lines black; dashed is inverted flight; the green dot is the start and the red
tick the end. Roll pieces integrated into loops are not coloured. Entries the
parser cannot read yet are listed as such.

The drawings are fetched with fetch_usg_drawings.py into DRAWINGS
(default ``.test-artifacts/usg-drawings``). Rendering needs matplotlib, which the
workspace environment does not have: this script runs itself again under
``uvx --with matplotlib`` for that step. Needs pdftoppm and pdftotext (poppler).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "data" / "f3a" / "usg_drawings.json"
DPI = 110
BAND_ABOVE, BAND_BELOW = 3, 68  # points around the entry's header line


# ------------------------------------------------------------ stage 1: templates


def dump_templates(groups: list[str], path: Path) -> None:
    import geometry as g
    import schemas.positioning as p
    from flightdata import State
    from schemas import aresti as a
    from tuning.builders import load_builder

    from pyolan.f3a import F3AParseError, parse_f3a_description

    builder = load_builder("f3a")
    result: dict[str, dict] = {}
    for entry in json.loads(FIXTURE.read_text()):
        if entry["group"] not in groups:
            continue
        item: dict = dict(description=entry["description"], k=entry["k"])
        try:
            parsed = parse_f3a_description(entry["description"], entry["number"], entry["k"])
            figs = parsed.figures if isinstance(parsed, a.Option) else [parsed]
            fig = figs[0]
            mdef = builder.create_mdef(fig)
            if "roll_option" in mdef.mps.data:
                mdef.mps.data["roll_option"].defaul = 0
            attitude = p.Orientation.UPRIGHT if entry["entry_attitude"] == "upright" else p.Orientation.INVERTED
            templates = mdef.create().create_template(
                g.Transformation(g.Euler(attitude, 0, p.Heading.RTOL), g.P0())
            )
            segs = []
            for name, state in templates.items():
                belly = state.att.transform_point(g.PZ())
                segs.append(
                    dict(name=name, x=state.pos.x.tolist(), z=state.pos.z.tolist(), inv=(belly.z > 0).tolist())
                )
            item |= dict(segs=segs, els=[e.kind for e in fig.elements], options=len(figs))
        except (F3AParseError, Exception) as exc:  # noqa: BLE001 - listed on the sheet
            item["error"] = f"{type(exc).__name__}: {exc}"[:160]
        result[entry["number"]] = item
    path.write_text(json.dumps(result))


# ------------------------------------------------------------ stage 2: drawings and sheet


def entry_rows(pdf: Path) -> dict[str, tuple[int, float, float]]:
    """Catalogue number -> (page, header x, header y) in points."""
    text = subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    rows: dict[str, tuple[int, float, float]] = {}
    page = 0
    for line in text.splitlines():
        if "<page " in line:
            page += 1
        m = re.search(r'xMin="([\d.]+)" yMin="([\d.]+)".*>([0-9A-Za-z]{1,2}\.\d{1,2})</word>', line)
        if m:
            number = m.group(3)
            group, item = number.split(".")
            key = f"{int(group):02d}.{int(item)}" if group.isdigit() else f"{group.upper()}.{int(item)}"
            rows.setdefault(key, (page, float(m.group(1)), float(m.group(2))))
    return rows


def crop(pdf: Path, page: int, x_max: float, y: float, work: Path):
    """The left-hand drawing column of one entry's row, as an image array."""
    import matplotlib.image as mpimg

    scale = DPI / 72
    top = max(0, y - BAND_ABOVE)
    base = work / f"crop_{pdf.stem}_{page}_{int(y)}"
    subprocess.run(
        [
            "pdftoppm", "-r", str(DPI), "-png", "-f", str(page), "-l", str(page), "-singlefile",
            "-x", "0", "-y", str(int(top * scale)),
            "-W", str(int((x_max - 6) * scale)), "-H", str(int((BAND_ABOVE + BAND_BELOW) * scale)),
            str(pdf), str(base),
        ],
        check=True,
    )
    return mpimg.imread(f"{base}.png")


def draw_template(ax, item: dict) -> None:
    if "error" in item:
        ax.text(0.5, 0.5, "not parsed yet\n" + item["error"], ha="center", va="center", fontsize=6, wrap=True)
        ax.axis("off")
        return
    for seg in item["segs"]:
        m = re.match(r"e_(\d+)(?:_(\d+))?$", seg["name"])
        kind = item["els"][int(m.group(1))] if m else "line"
        colour = "tab:red" if (m and m.group(2) is not None) else {"loop": "tab:blue"}.get(kind, "k")
        x, z, inv = seg["x"], seg["z"], seg["inv"]
        for i in range(len(x) - 1):
            ax.plot(x[i : i + 2], z[i : i + 2], color=colour, ls="--" if inv[i] else "-", lw=1.4)
    first, last = item["segs"][0], item["segs"][-1]
    ax.plot([first["x"][0]], [first["z"][0]], "go", ms=4)
    ax.plot([last["x"][-1]], [last["z"][-1]], "r|", ms=9)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=5)


def render(group: str, templates: dict, drawings: Path, out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pdf = drawings / f"Group_{group}.pdf"
    rows = entry_rows(pdf)
    numbers = list(templates)
    per_row = 2
    n_rows = -(-len(numbers) // per_row)
    fig, axes = plt.subplots(n_rows, per_row * 2, figsize=(per_row * 7.5, n_rows * 2.3), squeeze=False)
    for ax in axes.flat:
        ax.axis("off")
    with tempfile.TemporaryDirectory() as tmp:
        for index, number in enumerate(numbers):
            r, c = divmod(index, per_row)
            drawing_ax, template_ax = axes[r][2 * c], axes[r][2 * c + 1]
            item = templates[number]
            drawing_ax.set_title(f"{number} K{item['k']}  {item['description'][:58]}", fontsize=6, loc="left")
            if number in rows:
                page, x, y = rows[number]
                drawing_ax.imshow(crop(pdf, page, x, y, Path(tmp)))
            template_ax.axis("on")
            draw_template(template_ax, item)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"group{group}.png"
    fig.tight_layout()
    fig.savefig(target, dpi=100)
    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("groups", nargs="*")
    parser.add_argument("--drawings", type=Path, default=Path(".test-artifacts/usg-drawings"))
    parser.add_argument("--out", type=Path, default=Path(".test-artifacts/f3a-review"))
    parser.add_argument("--render", type=Path, help=argparse.SUPPRESS)  # stage 2, run under matplotlib
    args = parser.parse_args(argv)
    groups = [g.upper() if g.isalpha() else f"{int(g):02d}" for g in args.groups]

    if args.render:
        templates = json.loads(args.render.read_text())
        for group in groups:
            wanted = {n: v for n, v in templates.items() if n.split(".")[0] == group}
            print(render(group, wanted, args.drawings, args.out))
        return 0

    missing = [g for g in groups if not (args.drawings / f"Group_{g}.pdf").exists()]
    if missing:
        sys.exit(
            f"no drawing for {missing} in {args.drawings}: run fetch_usg_drawings.py "
            f"{args.drawings} {' '.join(missing)}"
        )
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "templates.json"
        dump_templates(groups, data)
        subprocess.run(
            [
                "uvx", "--with", "matplotlib", "python", str(Path(__file__).resolve()),
                *groups, "--drawings", str(args.drawings), "--out", str(args.out), "--render", str(data),
            ],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
