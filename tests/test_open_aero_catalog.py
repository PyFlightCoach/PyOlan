"""Compare PyOlan's primitive catalogue with OpenAero's figure catalogue.

The OpenAero source is not a runtime dependency, so this is a checked-in
snapshot of the alphabetic base codes extracted from
``data/figures/figures.js``. Roll and attitude markers are normalized away.
"""

from pyolan.primitives import olan_figs


OPEN_AERO_BASE_CODES = {
    "Bb",
    "Bpb",
    "a",
    "ac",
    "aj",
    "ao",
    "b",
    "bB",
    "bb",
    "bh",
    "bpB",
    "bpb",
    "bz",
    "c",
    "cc",
    "cm",
    "co",
    "cv",
    "d",
    "db",
    "df",
    "dh",
    "dhd",
    "dif",
    "dvd",
    "dvz",
    "dz",
    "g",
    "gg",
    "h",
    "hat",
    "hd",
    "hp",
    "j",
    "jijo",
    "jj",
    "jjoi",
    "jio",
    "jo",
    "joi",
    "joj",
    "joji",
    "jojio",
    "jojo",
    "jw",
    "k",
    "kz",
    "m",
    "mj",
    "mm",
    "n",
    "o",
    "oaj",
    "oajj",
    "oajjj",
    "oajjjj",
    "oj",
    "or",
    "p",
    "pBb",
    "pBpb",
    "pb",
    "pbB",
    "pbh",
    "pbb",
    "pbpB",
    "pbpb",
    "ph",
    "pn",
    "pp",
    "q",
    "qo",
    "rao",
    "rcc",
    "rbz",
    "rc",
    "rdb",
    "ro",
    "rp",
    "rpp",
    "rqq",
    "rq",
    "ry",
    "ryz",
    "rzb",
    "t",
    "ta",
    "th",
    "tri",
    "v",
    "vc",
    "vf",
    "vif",
    "vis",
    "vs",
    "vv",
    "w",
    "xa",
    "xm",
    "y",
    "z",
    "zb",
    "zt",
    "zy",
}

# Roll-only patterns, not primitive figures: OpenAero's "f" field entry and the
# d/iv lines with a snap or spin (e.g. "+d2if", "iv1is"), which normalize to
# d/v plus the roll letters. PyOlan reads those as the line figure and a roll.
OPEN_AERO_ROLL_ONLY_CODES = {"f", "df", "dif", "vf", "vif", "vs", "vis"}


def test_open_aero_catalog_gap_is_explicit():
    """Every normalized OpenAero base code has a PyOlan representation."""
    figure_codes = OPEN_AERO_BASE_CODES - OPEN_AERO_ROLL_ONLY_CODES
    unsupported = figure_codes - set(olan_figs)

    assert unsupported == set()
