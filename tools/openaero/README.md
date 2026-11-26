# OpenAero reference harness

PyOlan's OpenAero tests compare PyOlan with OpenAero's own trace of each figure.
This directory holds the tools that produce those expectations. Node is needed
only to refresh them; the tests read the committed files and never run Node.

| File | What it does |
| --- | --- |
| `OPENAERO_SHA` | The pinned upstream commit of `https://github.com/OpenAero/main`. |
| `fetch_openaero.sh` | Fetches that commit into `.test-artifacts/openaero/<sha>` (or `$OPENAERO_DIR`). |
| `package.json` | Pins jsdom. Run `npm ci` here once. |
| `oa-trace.js` | Loads OpenAero headless and records every figure's buildShape calls, K and directions. |
| `export-figures.js` | Exports the figure catalogue (`tests/data/openaero/figures.json`). |
| `export.py` | Generates the corpora, runs the harness and writes the expectations. |
| `add_regression.py` | Adds a user-reported OLAN sequence to the `regressions` corpus. |
| `propose_findings.py` | Triage report: groups the current failures of the `openaero` lane by finding (`findings.json`). |

## Refresh

From the PyOlan package directory, with the workspace venv:

```sh
(cd tools/openaero && npm ci)
../../.venv/bin/python tools/openaero/export.py          # everything, about 90 s
../../.venv/bin/python tools/openaero/export.py library  # one corpus
```

`export.py` writes:

- `tests/data/openaero/figures.json`: the catalogue, with provenance;
- `tests/data/openaero/sequence_directions.json`: the `[directions]` lines of
  `regressions.txt`, for `test_direction.py`;
- `tests/data/openaero/expected/<corpus>.json.gz`: each figure's aresti numbers,
  powered and glider K, entry and exit direction and attitude, canonical form
  (`tests/openaero/canonical.py`), snap and spin negative flags and correction
  rolls.

The raw traces are kept in `.test-artifacts/openaero/traces`. After a change to
`canonical.py`, `export.py --reuse-traces` re-applies it without running OpenAero.

The corpora:

- `library`: the 364 sequences of OpenAero's `data/library.js`. Each link is
  loaded, then its text is rebuilt in Form B, because a link may select grid view
  (G restarts every figure) or Form C (mirrored rolls).
- `catalogue`: every catalogue pattern with empty slots, three seeded fills per
  slot, and class-boundary fills (`4`, `3`, `34` on `&` slots, spins on `$` slots),
  20 figures to a sequence separated by `//`.
- `syntax`: a fixed set of figures with drawing characters, line extensions,
  comments, labels, entry commands, moves, switches and separators.
- `regressions`: `tests/data/openaero/regressions.txt`.

## Harness settings

- Form B; the rules worker is stubbed, so K is OpenAero's rule-free K (no `kRules`).
- "Non-Aresti rolls" is on, so OpenAero draws every roll as written. With it off
  (OpenAero's default) a roll outside the Aresti catalogue, such as a half spin, is
  drawn as a line.
- Each sequence runs in its own sporting class, then again in the other class for
  the other K.

## A new difference

```sh
../../.venv/bin/python tools/openaero/add_regression.py 'OLAN sequence' --comment 'user report, date'
../../.venv/bin/python ../../scripts/test.py openaero --package PyOlan --timeout 900
../../.venv/bin/python tools/openaero/propose_findings.py   # failures grouped by finding
```

There is no list of accepted differences: a new difference is a failing test in the
`openaero` lane until it is fixed. `propose_findings.py` guesses a finding ID
(`findings.json`) from simple rules, so a fix can record the counts before and after
(`--json PATH`); review the guesses, and work out the cause of every one it marks `?`.

## A new OpenAero commit

Change `OPENAERO_SHA` (and `HARNESS_VERSION` in `oa-trace.js` if the harness
output changes), run `export.py`, and review the change in the expectations and
in the differential tests before committing.
