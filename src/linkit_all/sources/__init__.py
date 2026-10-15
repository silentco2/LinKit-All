from linkit_all.sources.ashby import Ashby
from linkit_all.sources.base import Source
from linkit_all.sources.greenhouse import Greenhouse
from linkit_all.sources.lever import Lever


def registry() -> dict[str, Source]:
    return {s.name: s for s in (Greenhouse(), Lever(), Ashby())}
