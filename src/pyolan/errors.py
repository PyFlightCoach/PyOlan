"""Errors raised while reading OLAN."""

from __future__ import annotations


class OlanParseError(ValueError):
    """OLAN that cannot be read.

    ``token`` is the OLAN item (a space separated word, a quoted comment kept whole)
    that could not be read, ``index`` its position among the items of the sequence
    (0 based), ``figure`` the number of the figure it would have been (1 based) and
    ``detail`` what is wrong with it. ``message`` puts them together for a pilot,
    for example: Figure 4 "2x-": "x" is not an OLAN roll.
    """

    code = "olan_parse_error"

    def __init__(
        self,
        detail: str,
        token: str | None = None,
        index: int | None = None,
        figure: int | None = None,
    ):
        self.detail = detail
        self.token = token
        self.index = index
        self.figure = figure
        super().__init__(self.message)

    @property
    def message(self) -> str:
        where = []
        if self.figure is not None:
            where.append(f"Figure {self.figure}")
        if self.token is not None:
            where.append(f'"{self.token}"')
        return f"{' '.join(where)}: {self.detail}" if where else self.detail

    def __str__(self) -> str:
        return self.message

    def at(self, token: str | None = None, index: int | None = None, figure: int | None = None) -> "OlanParseError":
        """The same error with its place in the sequence filled in."""
        return OlanParseError(
            self.detail,
            self.token if token is None else token,
            self.index if index is None else index,
            self.figure if figure is None else figure,
        )

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "token": self.token, "index": self.index}


class NoFigureLeft(Exception):
    """Only drawing commands are left: the end of the sequence, not an error."""
