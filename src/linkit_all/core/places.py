"""Places you would work -> everything derived from them, in one place.

`PUT /api/search` calls `apply_places` so `search.locations`, the location and work-mode filters,
the Indeed country and the saved answers (`authorized_countries`, `visa_countries`,
`willing_to_relocate`) can never disagree with the places list.
"""

from linkit_all.apply.answers import ApplicationAnswers, canonical_country, iso2_of
from linkit_all.core import geo
from linkit_all.core.presets import country_preset
from linkit_all.core.search import WORK_MODES, Place, SearchConfig


def apply_places(cfg: SearchConfig, prev: list[Place]) -> SearchConfig:
    """`cfg` with the fields derived from its places; unchanged when there are none.

    `prev` are the places saved before: clearing them all resets the location fields."""
    places = cfg.search.places
    if not places and not prev:
        return cfg
    s = cfg.search.model_copy()
    # No places left means "anywhere": a lone "Remote" would filter to remote jobs only.
    labels = list(dict.fromkeys([p.label for p in places] + ["Remote"] * bool(places and s.remote)))
    s.locations = labels or [""]
    filters = cfg.filters.model_copy(
        update={
            "locations": [x.lower() for x in labels],
            "work_modes": list(WORK_MODES) if s.remote else ["hybrid", "onsite"],
        }
    )
    sources = cfg.sources
    if key := next((k for p in places if (k := country_preset(p.country).jobspy)), ""):
        sources = sources.model_copy(update={"jobspy_country": key})
    return cfg.model_copy(update={"search": s, "filters": filters, "sources": sources})


def places_answers(
    a: ApplicationAnswers, places: list[Place], prev: list[Place], home_country: str
) -> ApplicationAnswers:
    """`a` with the country lists and the relocation default taken from `places`."""
    if not places and not prev:
        return a
    out = a.model_copy()
    if places:
        out.authorized_countries = _countries(places, "allowed")
        out.visa_countries = _countries(places, "visa")
        away = any(p.country and p.country != home_country.upper() for p in places)
        if out.willing_to_relocate is None and home_country and away:
            out.willing_to_relocate = True
    else:  # cleared: drop only what the old places had put there
        gone = {canonical_country(p.country) for p in prev if p.country}
        keep = [c for c in a.authorized_countries if canonical_country(c) not in gone]
        out.authorized_countries = keep
        out.visa_countries = [c for c in a.visa_countries if canonical_country(c) not in gone]
    return out


def _countries(places: list[Place], work: str) -> list[str]:
    return list(dict.fromkeys(p.country for p in places if p.work == work and p.country))


def synthesize_places(cfg: SearchConfig, home_country: str) -> SearchConfig:
    """Old configs have only `search.locations`: show them as places (nothing is saved).

    All become "allowed": we cannot know which ones would need a visa."""
    s = cfg.search
    if s.places:
        return cfg
    labels = [x for x in dict.fromkeys(s.locations) if x.strip() and x.strip().lower() != "remote"]
    if not labels:
        return cfg

    def iso(label: str) -> str:
        found = geo.country(label)
        return found.iso2 if found else iso2_of(label) or home_country.upper()

    places = [Place(label=x, country=iso(x), work="allowed") for x in labels]
    remote = "remote" in cfg.filters.work_modes
    found = s.model_copy(update={"places": places, "remote": remote})
    return cfg.model_copy(update={"search": found})
