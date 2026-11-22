"""Pure functions of scripts/crop_usg_drawings.py, on synthetic inputs."""

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "crop_usg_drawings", Path(__file__).resolve().parent.parent / "scripts" / "crop_usg_drawings.py")
crop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crop)

BBOX = """<page width="595.28" height="841.89">
<word xMin="209.7" yMin="110.5" xMax="219.4" yMax="115.2">j.1</word>
<word xMin="209.7" yMin="127.5" xMax="219.4" yMax="132.2">Turnaround</word>
<word xMin="209.7" yMin="197.2" xMax="219.4" yMax="201.8">j.2</word>
</page>
<page width="595.28" height="841.89">
<word xMin="209.7" yMin="50.0" xMax="219.4" yMax="55.0">01.9</word>
<word xMin="209.7" yMin="150.0" xMax="219.4" yMax="155.0">1.10</word>
"""


def placed(page, left, top, width=113, height=84):
    return crop.Placed(page, left, top, width, height, Path("x.png"))


def test_number_key():
    assert crop.number_key("j.1") == "J.1"
    assert crop.number_key("1.9") == "01.9"
    assert crop.number_key("01.10") == "01.10"


def test_entry_rows():
    rows = crop.entry_rows(BBOX)
    assert rows == {"J.1": (1, 110.5), "J.2": (1, 197.2), "01.9": (2, 50.0), "01.10": (2, 150.0)}


def test_slot_of():
    assert crop.slot_of(placed(1, 422, 108), 595.28) == crop.SLOT_LTOR  # right column
    assert crop.slot_of(placed(1, 60, 108), 595.28) == crop.SLOT_RTOL  # left column


def test_match_rows_by_position():
    rows = crop.entry_rows(BBOX)
    logo = placed(1, 60, 8, 66, 67)  # above every header
    images = [logo, placed(1, 60, 108), placed(1, 422, 108), placed(1, 60, 195), placed(2, 422, 47), placed(2, 60, 148)]
    found = crop.match_rows(rows, images, 595.28)
    assert set(found) == {("J.1", 2), ("J.1", 1), ("J.2", 2), ("01.9", 1), ("01.10", 2)}
    assert found[("J.1", 1)] is images[2]


def test_match_rows_ignores_other_page():
    rows = crop.entry_rows(BBOX)
    assert crop.match_rows(rows, [placed(3, 422, 108)], 595.28) == {}


def test_trim_greyscale_with_margin():
    arr = np.full((100, 200, 3), 255, np.uint8)
    arr[40:50, 60:90] = 0
    out = crop.trim(Image.fromarray(arr))
    assert out.mode == "L"
    assert out.size == (30 + 2 * crop.MARGIN, 10 + 2 * crop.MARGIN)


def test_trim_blank_unchanged():
    assert crop.trim(Image.new("RGB", (20, 10), "white")).size == (20, 10)


def test_crop_name():
    assert crop.crop_name("01.9", 1) == "01.9_1.png"
    assert crop.crop_name("J.10", 2) == "J.10_2.png"


def test_usg_numbers_mapped_to_catalogue():
    assert crop.crop_name("Q.8", 1) == "Q.9_1.png"
    assert crop.crop_name("Q.7", 2) == "Q.8_2.png"
    assert crop.crop_name("Q.6", 1) == "Q.6_1.png"
