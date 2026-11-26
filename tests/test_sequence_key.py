"""sequence_key: two OLAN strings are the same sequence exactly when their keys are equal."""

import pytest

from pyolan.errors import OlanParseError
from pyolan.sequence_key import figure_keys, sequence_key

pytestmark = pytest.mark.unit

# The same five figures, drawn (positions, scale, line lengths, "+" markers) and plain.
DRAWN = (
    "2% `````4,3if``ry.'22 /~~+++..''1.'n('5if,3.).,8.---~ (13,8) "
    "-```5is';3..''iBb(``````````4',2`)....1~~ 2% o42 .''1'm44,if-~~ "
)
PLAIN = "4,3ifry22 1n(5if,3),8- -5is;3iBb(4,2)1 o42 1m44,if-"


def test_drawing_is_ignored():
    assert sequence_key(DRAWN) == sequence_key(PLAIN)


def test_each_figure_has_one_entry_and_one_exit_marker():
    assert figure_keys(PLAIN) == [
        "+4,3ifry22+",
        "+1n(5if,3),8-",
        "-5is;3iBb(4,2)1+",
        "+o42+",
        "+1m44,if-",
    ]


@pytest.mark.parametrize(
    "other",
    [
        "+4,3ifry22+ +1n(5if,3),8--- -5is;3iBb(4,2)1 o42 1m44,if-",  # explicit and repeated markers
        "eu 4,3ifry22 ej 1n(5if,3),8- -5is;3iBb(4,2)1 o42 1m44,if-",  # entry markers
        '"Known" 4,3ifry22 1n(5if,3),8- @A -5is;3iBb(4,2)1 // o42 1m44,if-',  # comments, labels
        "  4,3ifry22\n1n(5if,3),8-   -5is;3iBb(4,2)1 o42 1m44,if-  ",  # spacing
    ],
)
def test_same_sequence_written_differently(other):
    assert sequence_key(other) == sequence_key(PLAIN)


@pytest.mark.parametrize(
    "other",
    [
        "4,3ifry22 1n(5if,3),8- -5is;3iBb(4,2)1 o42 1m44,f-",  # a different roll
        "4,3ifry22 1n(5if,3),8- -5is;3iBb(4,2)1 o4 1m44,if-",  # fewer points
        "1n(5if,3),8- 4,3ifry22 -5is;3iBb(4,2)1 o42 1m44,if-",  # another order
        "4,3ifry22 1n(5if,3),8- -5is;3iBb(4,2)1 o42",  # a figure fewer
        "4,3ifry22 1n(5if,3),8- -5is;3iBb(4,2)1 -o42- 1m44,if-",  # inverted
    ],
)
def test_different_sequences(other):
    assert sequence_key(other) != sequence_key(PLAIN)


def test_unreadable_olan_raises():
    with pytest.raises(OlanParseError):
        sequence_key("4,3ifry22 xyzzy o")


def test_drawing_only_is_empty():
    assert sequence_key("2% (3,4) ~~ //") == ""
