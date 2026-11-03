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

TODO:
- Validate generated geometry and roll placement for the extended OpenAero
  field codes listed in `tests/test_open_aero_catalog.py`.
- Refresh the pinned OpenAero fixture with:
  `node ../../../OpenAero/tools/export-figure-catalog.js tests/data/openaero/figures.json`.
- The fixture includes source structural tokens (roll markers and drawing
  shapes) for differential checks without making OpenAero a runtime dependency.
- Render plans distinguish independent rolls (`_`) from embedded looping rolls
  (`!`); use these plans when validating primitive element counts and roll
  placement.
- Modify so it respects the correct olan figure directions (prefers turnarounds when there is ambiguity)
- Consider closer links with open-aero. Would it be better to read .seq files?
- Add K factor calculation
- Think about positioning the generated templates so they fit in the box better (probably better handled in the FlightAnalysis submodule).
- 