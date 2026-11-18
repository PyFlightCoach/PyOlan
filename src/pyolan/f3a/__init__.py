"""Parse F3A unknown catalogue descriptions (FAI sporting code Annex 5G)."""

from .errors import F3AParseError
from .parser import parse_f3a_description

__all__ = ["F3AParseError", "parse_f3a_description"]
