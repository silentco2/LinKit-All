"""Route a pasted career URL (or page HTML) to the ATS that hosts its jobs.

The patterns live on the ATS plugins (`Source.url_patterns`); this module only combines them.
"""

import re
from collections.abc import Iterable
from functools import lru_cache

from linkit_all.sources.base import Source

_NOT_SLUGS = {"embed", "v1", "jobs", "api", "www", "oneclick-ui"}


@lru_cache(maxsize=1)
def _default_sources() -> tuple[Source, ...]:
    from linkit_all.sources import registry  # late: plugins (jobspy) import this module

    return tuple(registry().values())


def detect(text: str, sources: Iterable[Source] | None = None) -> tuple[str, str] | None:
    """(ats, board slug) from a URL, "ats:slug" shorthand, or any text such as page HTML.
    `sources` defaults to every registered plugin; patterns are tried plugin by plugin (sorted
    by module name), each plugin's own patterns in the order it lists them."""
    ats = [s for s in (_default_sources() if sources is None else sources) if s.kind == "ats"]
    names = "|".join(re.escape(s.name) for s in ats)
    if names and (m := re.match(rf"^({names}):(.+)$", text.strip())):
        return m.group(1), m.group(2)
    for s in ats:
        for pattern in s.url_patterns:
            for m in pattern.finditer(text):
                if m.group(1).lower() not in _NOT_SLUGS:
                    return s.name, "/".join(m.groups())
    return None
