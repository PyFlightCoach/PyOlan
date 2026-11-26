# PyOlan

PyOlan reads OLAN (One Letter Aerobatic Notation, https://openaero.net/) sequences,
as typed into OpenAero or held in an AcroWRX file, and builds the figures FCScore
scores: a `schemas.aresti` figure, its definition, manoeuvre and template, and the
K factor. It also turns F3A unknown catalogue descriptions into figures
(`pyolan.f3a`, below).

PyOlan is part of the FCScoreFuture workspace and is installed with it; it is not
published to PyPI.

## Reading a sequence

`parse_olan` needs a rule set's builder (from Tuning) and the wind direction:

```python
from schemas.positioning import Heading
from tuning.builders import load_builder

from pyolan.errors import OlanParseError
from pyolan.parser import parse_olan

builder = load_builder("IAC", category="advanced")
try:
    figures = parse_olan("o 4h4 dq", builder, Heading.RTOL)
except OlanParseError as error:
    print(error.message, error.token, error.index)
else:
    for figure in figures:  # ParsedOlanFig
        print(figure.short_name, figure.aresti.info.k, figure.warnings)
```

Each `ParsedOlanFig` holds the figure as read (`olan`), the aresti figure, the
definition, the manoeuvre, its template and the warnings. The templates are chained:
each figure starts where the one before it ends.

`OlanFig.take` reads one figure from the items of a sequence
(`pyolan.drawing.olan_items`), skipping drawing commands, and needs no builder.
`pyolan.sequence_key.sequence_key` gives a form of a sequence without its drawing,
for finding the same sequence again.

## What it reads, and how

The reference is OpenAero: a figure PyOlan builds is the figure OpenAero draws from
the same OLAN (elements, rolls, entry and exit attitude and direction, and K).

- **Geometry** comes from OpenAero's drawing string for the catalogue variant
  OpenAero chooses (`drawn.py`, `direction.py`). Rolling turns and roll-only figures
  use hand-written elements (`primitives.py`).
- **K** is OpenAero's: the base figure's K plus the K of each roll, powered or glider
  (`OlanFig.k_powered`, `k_glider`). OpenAero's rule-specific K (`kRules`, used by
  the French rule sets for some rolling turns) is not applied.
- **Turns** can be flown either way. A turn or rolling turn carries both in
  `ndmps["roll_option"]`; option 0 is the way OpenAero draws it. Rolls on a vertical
  line that decide the exit direction are linked the same way.
- **Sizes** are not read from the rules: PyOlan creates no loop radius or line length
  ManParms, so the sides and radii of a figure are not compared with each other.

## Errors and warnings

Nothing is skipped silently. `parse_olan` raises `OlanParseError` (a `ValueError`)
for anything that is neither a figure nor a drawing command, and for a figure it
cannot build. The error carries the item (`token`), its position among the items of
the sequence (`index`), the figure number and a `message` written for a pilot.

Two cases differ from OpenAero on purpose:

- **A sequence that does not link raises.** Each figure must start in the attitude
  the figure before it ends in. OpenAero corrects the entry and draws on; PyOlan
  inserts no half roll or turnaround between figures. An OpenAero free known file
  lists only the compulsory figures, so it cannot be read as a sequence.
- **OpenAero's non-Aresti figures raise** (its Family 0: the wingover `jw`, the clover
  leaves `oj` and `ioj`, `mj`, `aj`, `4j5`, `4jo5`, the point tip `th`, `vv`, `hat`,
  `hp`, `iph`, `ibh`, `ipbh`, `tri`, `xm`, `xa` and `oaj`, upright or inverted), under
  every rule set, with a message that lists them all (`figure_parser.NON_ARESTI`).

Codes that are not OpenAero figures (once PyOlan's own, such as `jj`, `bh` or `ph`)
raise too, as do figures OpenAero rejects, usually for a missing `-` attitude marker.

`parse_olan(olan, builder, wind, sizing=tuning.builders.sizing_info(rules))` links the
sizes the rules compare (`sizing.py`): the part-loops OpenAero draws as round elements
share `loop_radius`, and the rule set's `[sizing]` table names the figures whose corners
and interior lines match too. Without `sizing` no size is linked.

`ParsedOlanFig.warnings` reports what was read differently from what was written, as
OpenAero does it:

- a roll the figure needs and the OLAN leaves out is added (a correction roll, as in
  `c` or `ao`);
- a roll written where the figure has no roll (`o(2)`) is ignored.

A template that leaves the box the other way from OpenAero is logged as a warning,
and the next figure starts on OpenAero's heading. That is not expected: add the
sequence to the regressions.

## OpenAero reference data

PyOlan does not need OpenAero or Node to run. Data taken from OpenAero is committed:

| File | Contents | Written by |
| --- | --- | --- |
| `src/pyolan/data/openaero_figures.json` | figure variants and their drawing strings | `scripts/generate_openaero_figures.py` |
| `src/pyolan/data/openaero_k.json` | base figure and roll K | `tools/openaero/export.py tables` |
| `tests/data/openaero/` | the figure catalogue, and OpenAero's own trace of the library, catalogue, syntax and regression corpora | `tools/openaero/export.py` |

The pinned OpenAero commit and the tools are described in
[tools/openaero/README.md](tools/openaero/README.md).

## Tests

Run from the FCScoreFuture root:

```sh
.venv/bin/python scripts/test.py unit --package PyOlan
.venv/bin/python scripts/test.py component --package PyOlan --timeout 900
```

The component lane compares PyOlan with OpenAero figure by figure, sequence by
sequence and, for a subset of the library, template by template under each rule set.
There is no list of accepted differences. The same comparison of every library
sequence's templates is a diagnostic selection of about four minutes:

```sh
.venv/bin/python scripts/test.py diagnostic --package PyOlan --timeout 900 \
    --select packages/PyOlan/tests/test_openaero_strict.py::test_template_library_all
```

When a pilot reports OLAN that is read wrongly, add it first:
`tools/openaero/add_regression.py` (see the tools README). The analysis server logs
the OLAN it refuses (`/parse_olan refused`).

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
