class F3AParseError(ValueError):
    """A catalogue description could not be parsed.

    The message names the words that were not understood, or the geometric
    constraint that could not be met, so no modifier is silently dropped.
    """
