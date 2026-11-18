from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

import geometry as g
import numpy as np
import schemas.positioning as p
from flightanalysis import ManDef, Manoeuvre
from flightanalysis.builders.manbuilder import ManBuilder
from flightdata import State
from schemas import aresti as a
from schemas import sequence_position

from .direction import DirectionState
from .figure_parser import OlanFig


@dataclass
class ParsedOlanFig:
    olan: OlanFig
    aresti: a.Figure
    definition: ManDef
    manoeuvre: Manoeuvre
    template: State

    @property
    def short_name(self):
        return self.aresti.info.short_name


def _turn_ndmps(olanfig: OlanFig) -> dict[str, list[list[float]]]:
    turn_options = olanfig.turn_options()
    return {"roll_option": turn_options} if turn_options is not None else {}


def _along_box(heading: p.Heading) -> bool:
    return heading in (p.Heading.RTOL, p.Heading.LTOR)


def _template(mdef: ManDef, itrans: g.Transformation, option: int = 0) -> State:
    if "roll_option" in mdef.mps.data:
        mdef.mps.data["roll_option"].defaul = option
    return State.stack(mdef.create().create_template(itrans), "element")


def _linked_figure(
    olanfig: OlanFig,
    mb: ManBuilder,
    info: a.ManInfo,
    itrans: g.Transformation,
    entry_heading: p.Heading,
    required: p.Heading | None,
) -> tuple[a.Figure, ManDef]:
    """Create the figure, linking the rolls of the direction-changing lines.

    Each direction-changing line takes one sign for all of its rolls. The sign
    combinations are pruned using the templates built from the entry transform:
    along the box, only the combinations that exit as required (OpenAero's exit
    direction, see direction.py) are kept; for a cross box entry both are kept so
    the analysis can choose, with the one that exits as required first. A cross
    box exit only emits roll_option when it links more than one element.
    """
    lines = olanfig.direction_lines()
    if not lines:
        figure = a.Figure(
            info=info,
            elements=olanfig.create_elements(use_roll_options=True),
            ndmps=_turn_ndmps(olanfig),
        )
        return figure, mb.create_mdef(figure)

    vectors = olanfig.roll_option_vectors()
    figure = a.Figure(
        info=info,
        elements=olanfig.create_elements(use_roll_options=True),
        ndmps={"roll_option": vectors},
    )
    mdef = mb.create_mdef(figure)
    exits = [
        p.Heading.infer(_template(mdef, itrans, i).att.bearing()[-1])
        for i in range(len(vectors))
    ]
    exit_along = _along_box(exits[0])
    keep = list(range(len(vectors)))
    if required is not None:
        matching = [i for i, e in enumerate(exits) if e == required]
        if _along_box(entry_heading) and exit_along:
            keep = matching or keep
        else:
            # the option that exits as required for the assumed entry comes first
            keep = matching + [i for i in keep if i not in matching]

    # a spin plus a roll on the same line become two elements that must stay linked
    rolls = olanfig.element_rolls()
    spans_elements = any(
        rolls[i].roll_arr[0].kind == "spin" and len(rolls[i].roll_arr) > 1
        for i in lines
    )
    if not (exit_along or spans_elements):
        # unlinked: the rolls are reversed as a whole if that is what OpenAero exits
        signs = list(itertools.product([1, -1], repeat=len(lines)))[keep[0]]
        flip = frozenset(i for i, sign in zip(lines, signs) if sign < 0)
        figure = figure.model_copy(
            update=dict(
                elements=olanfig.create_elements(
                    use_roll_options=True, link_lines=False, flip_lines=flip
                ),
                ndmps={},
            )
        )
        return figure, mb.create_mdef(figure)

    if keep != list(range(len(vectors))):
        figure = figure.model_copy(
            update=dict(ndmps={"roll_option": [vectors[i] for i in keep]})
        )
        mdef = mb.create_mdef(figure)
    mdef.mps.data["roll_option"].defaul = 0
    return figure, mdef


def parse_olan(
    data: str, mb: ManBuilder, wind: p.Heading = p.Heading.LTOR
) -> list[ParsedOlanFig]:
    data = data.split()
    figs: list[ParsedOlanFig] = []
    itrans = None
    state = DirectionState()

    while data:
        try:
            olanfig, data = OlanFig.take(data)
        except Exception:
            break

        # OpenAero's direction state gives the entry and the required exit heading
        oa = state.apply(olanfig)

        # make sure short_name is unique
        _suffix = ""
        while f"{olanfig.fig.short_name}{_suffix}" in [
            f.aresti.info.short_name for f in figs
        ]:
            _suffix = str(int(_suffix) + 1) if _suffix else "2"

        # Take the initial heading from the end of the previous figure if possible;
        # otherwise infer it from the wind direction and drawing parameters.
        if itrans:
            entry_heading = p.Heading.infer(itrans.att.bearing()[-1])
        elif oa.resolved:
            entry_heading = oa.entry_heading(wind)
        else:
            entry_heading = olanfig.entry_direction.wind_swap_heading(wind.reverse())
        required = oa.exit_heading(wind) if oa.resolved else None

        # need to get the direction (upwind / downwind / cross) from the heading and the wind
        entry_direction = p.Direction.parse_heading(entry_heading, wind)

        # if itrans cannot be picked up from the previous manouevre assume the olan figure is correct
        if not itrans:
            itrans = g.Transformation(g.Euler(olanfig.entry, 0, entry_heading), g.P0())

        arestifig, mdef = _linked_figure(
            olanfig,
            mb,
            olanfig.create_maninfo(
                f"{olanfig.fig.short_name}{_suffix}", entry_direction, None
            ),
            itrans,
            entry_heading,
            required,
        )
        man = mdef.create()
        tp = State.stack(man.create_template(itrans), "element")

        # The next figure starts where option 0 of this one finishes. If the
        # geometry leaves along the box in the wrong direction (a figure without
        # roll options that does not turn out as OpenAero says) the next figure
        # still starts as required.
        itrans = g.Transformation(tp.att[-1], g.P0())
        actual = p.Heading.infer(tp.att.bearing()[-1])
        if (
            required is not None
            and _along_box(required)
            and _along_box(actual)
            and actual != required
        ):
            itrans = g.Transformation(g.Euler(olanfig.exit, 0, required), g.P0())

        # update maninfo with the correct centre now that we know the exit direction.
        # OpenAero's exit is used when it is known, so that a cross box entry states
        # the along box exit rather than whatever option 0 happens to give.
        exit_heading = (
            required
            if required is not None
            else p.Heading.infer(tp.att.bearing()[-1])
        )
        arestifig.info = olanfig.create_maninfo(
            f"{olanfig.fig.short_name}{_suffix}",
            entry_direction,
            p.Direction.parse_heading(exit_heading, wind),
        )
        # The definition was built before the exit was known. Keep the builder's
        # centre points but take the final position and directions, which the
        # analysis uses (e.g. the cross box exit constraint).
        mdef = replace(
            mdef,
            info=mdef.info.model_copy(
                update=dict(
                    position=arestifig.info.position,
                    start=arestifig.info.start,
                    end=arestifig.info.end,
                )
            ),
        )

        figs.append(ParsedOlanFig(olanfig, arestifig, mdef, man, tp))

    if len(figs) == 0:
        raise Exception("No valid figures found in OLAN data")

    # Rules that judge the line before the first figure and after the last one need each
    # figure's place in the sequence, both in the figure that is stored and in its definition.
    if mb.uses_sequence_position:
        for i, fig in enumerate(figs):
            position = sequence_position(i, len(figs))
            fig.aresti.info.sequence_position = position
            fig.definition = mb.with_sequence_position(fig.definition, position)

    return figs
