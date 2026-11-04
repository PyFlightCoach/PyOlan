from __future__ import annotations

from dataclasses import dataclass

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


def _roll_ndmps(olanfig: OlanFig) -> dict[str, list[list[float]]]:
    angles = []
    for roll in olanfig.element_rolls():
        if roll is None or not roll.roll_arr:
            continue
        angles.extend(np.atleast_1d(roll.angles()).astype(float).tolist())
    options: list[list[float]] = [angles]
    if (
        angles
        and olanfig.fig.chars in {"j", "ji", "jo", "jio", "joi"}
        and len(angles) == 1
    ):
        turn = olanfig.fig.oels[0].turnamount * 2 * np.pi
        options = [[turn, angles[0]], [-turn, -angles[0]]]
    return {"roll_option": options} if angles else {}


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
            _suffix = int(_suffix) + 1 if len(_suffix) else "2"

        # Take the initial heading from the end of the previous figure if possible;
        # otherwise infer it from the wind direction and drawing parameters.
        entry_heading = (
            p.Heading.infer(itrans.att.bearing()[-1])
            if itrans
            else olanfig.entry_direction.wind_swap_heading(wind.reverse())
        )

        # need to get the direction (upwind / downwind / cross) from the heading and the wind
        entry_direction = p.Direction.parse_heading(entry_heading, wind)

        arestifig = a.Figure(
            info=olanfig.create_maninfo(
                f"{olanfig.fig.short_name}{_suffix}", entry_direction, None
            ),
            elements=olanfig.create_elements(use_roll_options=True),
            ndmps=_roll_ndmps(olanfig),
        )

        mdef = mb.create_mdef(arestifig)
        man = mdef.create()

        # if itrans cannot be picked up from the previous manouevre assume the olan figure is correct
        if not itrans:
            itrans = g.Transformation(g.Euler(olanfig.entry, 0, entry_heading), g.P0())

        tp = State.stack(man.create_template(itrans), "element")
        exit_direction = None

        if np.any(olanfig.can_swap_exit()) and p.Heading.infer(
            tp.att.bearing()[-1]
        ) in [
            p.Heading.RTOL,
            p.Heading.LTOR,
        ]:
            # If there is a 1/4 roll on a vertical line make sure the next manoeuvre
            # starts in the correct direction
            exit_heading = (
                entry_heading.reverse()
                if olanfig.fig.turnable is not None and not olanfig.exit_downwind
                else (p.Heading.LTOR if olanfig.exit_downwind else p.Heading.RTOL)
            )
            exit_direction = p.Direction.parse_heading(exit_heading, wind)
            itrans = g.Transformation(
                g.Euler(
                    olanfig.entry,
                    0,
                    exit_heading,
                )
            )

        else:
            # if not just take the exit direction from the end of this one
            itrans = g.Transformation(tp.att[-1], g.P0())

        # update maninfo with the correct centre now that we know the exit direction
        arestifig.info = olanfig.create_maninfo(
            f"{olanfig.fig.short_name}{_suffix}",
            entry_direction,
            exit_direction or p.Direction.parse_heading(tp.att.bearing()[-1], wind),
        )

        figs.append(ParsedOlanFig(olanfig, arestifig, mdef, man, tp))

    if len(figs) == 0:
        raise Exception("No valid figures found in OLAN data")

    return figs
