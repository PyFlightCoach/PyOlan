"""Drawing commands aren't used, but they need to be recognised so as not to process them as a figure"""
import re


re_dpre = dict(
    entry=r"^(ed|ej|eja|eu)$",
    subsequence=r"^//$",
    # a move may be preceded by > (move forward); it is not a direction switch
    move=r"^>*(\[|\()-?‑?\d+,-?‑?\d+(\]|\))$",
    scale=r"^-?\d+%$",
    offset=r"^(^|\d+)\>$",
    cross_switch=r"^\^$",
    y_direction=r"^/$",
    # lines, extensions and shortenings on their own ("~", "+++", "``", "''")
    line_length=r"^[~+/`'.]+$",
    comment=r"^\"[^\"]*\"$",
    freeuk=r"^@[A-L]$",
)

# Drawing commands that may be found on their own:
re_drawing = re.compile(rf"({'|'.join(re_dpre.values())})")

# Drawing commands within a figure:
re_draw = re.compile(r"[>/~+^'`.]")

# A comment is quoted and may contain spaces; it can also sit inside a figure.
re_comment = re.compile(r'"[^"]*"')
_re_item = re.compile(r'(?:"[^"]*"|[^\s"])+')


def strip_comments(text: str) -> str:
    return re_comment.sub("", text)


def olan_items(text: str) -> list[str]:
    """Split OLAN into items on white space outside comments.

    '"a comment" 4h4' is two items, the comment kept whole. A quote that is never
    closed raises OlanParseError.
    """
    from .errors import OlanParseError

    if text.count('"') % 2:
        start = text.rfind('"')
        raise OlanParseError("a comment is not closed (no second \")", text[start:start + 20], None)
    return _re_item.findall(text)
