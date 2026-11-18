# PyOlan

This WIP package contains a OLAN (One Letter Aerobatic Notation, https://openaero.net/) parser written in Python. The OLAN string is interpreted as a set of elements (loop, line, stallturn, spin etc). This is currently used by FCScore (https://www.flightcoach.org/fcscore/) to generate sequence definitions for automatic scoring.


Installation
```
    pip install pyolan
```

Install from source
```
    pip install -e .
```

Read the next figure from an olan string:
```
    from pyolan.figure_parser import OlanFig

    ostr = "/d'1 5% 2a,f (-3,6) 4h4^> p(2)...' dq"
    olan_array = ostr.split(" ")
    ofig, olan_array = OlanFig.take(olan_array)
```


parse an entire olan sequence, join the templates into one and plot:
```
    from flightdata import State
    from pyolan.parser import parse_olan

    olans: list[ParsedOlanFig] = parse_olan(
        "/d'1 5% 2a,f (-3,6) 4h4^> p(2)...' dq 4% 2b.''1.''+``` (-13,0) 3% ~2g~ (2,0) 3% iv```6s.....'' 22y````1.. (-3,0) 8% `24'zt`8''",
    )

    template = State.stack({fig.definition.info.short_name: fig.template for fig in olans}, "manoeuvre")

    template.plotlabels("manoeuvre").show()
```

OpenAero compatibility
----------------------

PyOlan keeps a pinned OpenAero catalogue at
`tests/data/openaero/figures.json`. It contains normalized attitudes, drawing
shapes, roll markers, render plans, and K factors without making OpenAero a
runtime dependency. Refresh it from a clean OpenAero checkout with:

```
node ../../../OpenAero/tools/export-figure-catalog.js \
    tests/data/openaero/figures.json
```

Render plans distinguish independent rolls (`_`) from embedded looping rolls
(`!`). The compatibility tests use this distinction when checking primitive
element counts and roll placement. The 36 renderer-only inverted variants are
explicitly excluded from PyOlan parsing and covered by
`test_renderer_only_open_aero_patterns_are_explicitly_out_of_scope`.
Marker-only roll slots are accepted as empty slots, so definitions such as
`+o_+` retain their loop geometry without creating an invalid roll element.

Parsed catalogue definitions expose their OpenAero K factors through
`OlanFig.k_powered`, `OlanFig.k_glider`, or
`OlanFig.k_factor(glider=True)`. Lookup is exact-definition based because K
factors vary with orientation and roll pattern; unknown/custom OLAN patterns
raise `ValueError`.

When a parsed figure contains numeric roll slots, `parse_olan` also emits the
roll angles in the Aresti definition's `ndmps["roll_option"]` metadata. Empty
marker-only slots are omitted.

Rolling-circle figures with a single roll expose paired turn and roll choices
in the same combination parameter. For example, `3jo3` emits
`[[3*pi/2, -6*pi], [-3*pi/2, 6*pi]]`; the loop angle references column zero
and its roll references column one.

Testing status
--------------

- OpenAero differential coverage includes signed, inverted, special-figure,
  multi-roll, and rolling-circle cases.
- Ambiguous turnable figures prefer an exit direction opposite to entry when
  no explicit exit marker overrides it.

Deferred work
-------------

- Consider whether direct `.seq` integration is preferable to the pinned
  catalogue for some workflows.
- Improve template positioning where this belongs in FlightAnalysis.

## F3A catalogue descriptions (`pyolan.f3a`)

`parse_f3a_description("01.9 Knife-edge loop from top (K6)")` turns an F3A unknown
catalogue line into a `schemas.aresti.Figure` (or an `Option`). The plan, conventions
and review decisions are in `docs/plans/f3a-unknown-import.md` in FCScoreFuture;
`tests/data/f3a/usg_drawings.json` holds the drawing metadata the tests check against and
`tests/data/f3a/implemented_groups.txt` lists the groups with a family.

Reviewing a group against the FAI USG drawings (run from the FCScoreFuture root; the drawings
are Roland Poidevin's, so they are downloaded to the untracked `.test-artifacts/` and not committed):

```sh
.venv/bin/python packages/PyOlan/scripts/fetch_usg_drawings.py .test-artifacts/usg-drawings 13 14
.venv/bin/python packages/PyOlan/scripts/f3a_review_sheet.py 13 14   # .test-artifacts/f3a-review/group13.png ...
```

Each sheet shows the drawing of every entry beside the f3a builder's template of the parsed figure.
