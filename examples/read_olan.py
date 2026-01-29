
from flightdata import State
from pyolan.parser import parse_olan
from tuning.builders import load_builder

mb = load_builder("IMAC")
olan = parse_olan(
    "o 12% 3> ``+````````2``rc+`````` 4> ',1~~ 2% 7> m2 (8,19) 1% id. 6% 8> h.' 8> ,2'b``,2' 12> v'2' (7,18) `````9s..'ik`` 3% 4> 2a",
    mb
)

for fig in olan:
    fig.template.plotlabels("element", nmodels=5).show()
