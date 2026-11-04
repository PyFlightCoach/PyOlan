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

Remaining work
--------------

- Extend differential roll-direction checks to more compound OpenAero render
  plans; canonical signed cases and geometry decomposition for `dz`, `dvz`, and
  `dvd` are covered.
- Prefer turnarounds when `parse_olan` has an ambiguous direction choice.
- Add roll-direction and other inter-figure constraints to generated Aresti
  definitions.
- Consider whether direct `.seq` integration is preferable to the pinned
  catalogue for some workflows.
- Improve template positioning where this belongs in FlightAnalysis.
