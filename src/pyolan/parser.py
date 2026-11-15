from __future__ import annotations

from dataclasses import dataclass, replace

import geometry as g
import numpy as np
import schemas.positioning as p
from flightanalysis import ManDef, Manoeuvre
from flightanalysis.builders.manbuilder import ManBuilder
from flightdata import State
from schemas import aresti as a

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


def _required_exit_heading(olanfig: OlanFig, entry_heading: p.Heading) -> p.Heading:
    return (
        entry_heading.reverse()
        if olanfig.fig.turnable is not None and not olanfig.exit_downwind
        else (p.Heading.LTOR if olanfig.exit_downwind else p.Heading.RTOL)
    )


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
) -> tuple[a.Figure, ManDef]:
    """Create the figure, linking the rolls of the direction-changing lines.

    Each direction-changing line takes one sign for all of its rolls. The sign
    combinations are pruned using the templates built from the entry transform:
    along the box, only the combinations that exit as required are kept; for a
    cross box entry both are kept so the analysis can choose. A cross box exit
    only emits roll_option when it links more than one element.
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
    if _along_box(entry_heading) and exit_along:
        required = _required_exit_heading(olanfig, entry_heading)
        keep = [i for i, e in enumerate(exits) if e == required] or keep

    # a spin plus a roll on the same line become two elements that must stay linked
    rolls = olanfig.element_rolls()
    spans_elements = any(
        rolls[i].roll_arr[0].kind == "spin" and len(rolls[i].roll_arr) > 1
        for i in lines
    )
    if not (exit_along or spans_elements):
        figure = figure.model_copy(
            update=dict(
                elements=olanfig.create_elements(use_roll_options=True, link_lines=False),
                ndmps={},
            )
        )
        return figure, mb.create_mdef(figure)

    if len(keep) < len(vectors):
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

    while data:
        try:
            olanfig, data = OlanFig.take(data)
        except Exception:
            break

        # make sure short_name is unique
        _suffix = ""
        while f"{olanfig.fig.short_name}{_suffix}" in [
            f.aresti.info.short_name for f in figs
        ]:
            _suffix = str(int(_suffix) + 1) if _suffix else "2"

        # Take the initial heading from the end of the previous figure if possible;
        # otherwise infer it from the wind direction and drawing parameters.
        entry_heading = (
            p.Heading.infer(itrans.att.bearing()[-1])
            if itrans
            else olanfig.entry_direction.wind_swap_heading(wind.reverse())
        )

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
        )
        man = mdef.create()
        tp = State.stack(man.create_template(itrans), "element")

        # The next figure starts where option 0 of this one finishes, and the
        # info agrees with the geometry.
        itrans = g.Transformation(tp.att[-1], g.P0())

        # update maninfo with the correct centre now that we know the exit direction
        arestifig.info = olanfig.create_maninfo(
            f"{olanfig.fig.short_name}{_suffix}",
            entry_direction,
            p.Direction.parse_heading(p.Heading.infer(tp.att.bearing()[-1]), wind),
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

    return figs
