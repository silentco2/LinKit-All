from linkit_all.sources.ashby import Ashby
from linkit_all.sources.base import Source
from linkit_all.sources.greenhouse import Greenhouse
from linkit_all.sources.jobspy_sites import jobspy_sources
from linkit_all.sources.lever import Lever
from linkit_all.sources.wuzzuf import Wuzzuf


def registry() -> dict[str, Source]:
    sources: list[Source] = [Greenhouse(), Lever(), Ashby(), *jobspy_sources(), Wuzzuf()]
    return {s.name: s for s in sources}
