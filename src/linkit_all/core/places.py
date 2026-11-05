"""Places you would work -> everything derived from them, in one place.

`PUT /api/search` calls `apply_places` so `search.locations`, the location and work-mode filters,
the Indeed country and the saved answers (`authorized_countries`, `visa_countries`,
`willing_to_relocate`) can never disagree with the places list. The work modes are the user's own:
`search.remote` follows them, never the other way round.
"""

from linkit_all.apply.answers import ApplicationAnswers, canonical_country, iso2_of
from linkit_all.core import geo
from linkit_all.core.presets import country_preset
from linkit_all.core.search import Place, SearchConfig


def consistent_work(places: list[Place]) -> list[Place]:
    """Work rights are per country: every row of a country gets the work right its last
    explicit ("allowed" / "visa") row states. A country with only "ask" rows stays "ask"."""
    stated = {p.country.upper(): p.work for p in places if p.country and p.work != "ask"}
    return [
        p.model_copy(update={"work": stated[p.country.upper()]})
        if p.country.upper() in stated and p.work != stated[p.country.upper()]
        else p
        for p in places
    ]


def apply_places(cfg: SearchConfig, prev: list[Place]) -> SearchConfig:
    """`cfg` with the fields derived from its places; unchanged when there are none.

    `prev` are the places saved before: clearing them all resets the location fields."""
    places = cfg.search.places
    if not places and not prev:
        return cfg
    s = cfg.search.model_copy(
        update={"remote": "remote" in cfg.filters.work_modes, "places": consistent_work(places)}
    )
    # No places left means "anywhere": a lone "Remote" would filter to remote jobs only.
    labels = list(dict.fromkeys([p.label for p in places] + ["Remote"] * bool(places and s.remote)))
    s.locations = labels or [""]
    filters = cfg.filters.model_copy(update={"locations": [x.lower() for x in labels]})
    sources = cfg.sources
    if key := next((k for p in places if (k := country_preset(p.country).jobspy)), ""):
        sources = sources.model_copy(update={"jobspy_country": key})
    return cfg.model_copy(update={"search": s, "filters": filters, "sources": sources})


def places_answers(
    a: ApplicationAnswers, places: list[Place], prev: list[Place], home_country: str
) -> ApplicationAnswers:
    """`a` with the country lists and the relocation default taken from `places`.

    Only explicit choices ("allowed" / "visa") count: an "ask" place changes nothing, and a
    country the places never mentioned keeps whatever the answers already say. A country that
    had an explicit place before and has none now is taken off both lists."""
    if not places and not prev:
        return a
    places = consistent_work(places)
    out = a.model_copy()
    now = _countries(places, "allowed") + _countries(places, "visa")
    gone = {canonical_country(c) for c in _countries(prev, "allowed") + _countries(prev, "visa")}
    gone -= {canonical_country(c) for c in now}
    allowed, visa = _countries(places, "allowed"), _countries(places, "visa")
    mine = {canonical_country(c) for c in allowed + visa}  # the places decide these countries
    drop = gone | mine
    out.authorized_countries = [
        c for c in a.authorized_countries if canonical_country(c) not in drop
    ] + allowed
    out.visa_countries = [c for c in a.visa_countries if canonical_country(c) not in drop] + visa
    away = any(c != home_country.upper() for c in now)
    if out.willing_to_relocate is None and home_country and away:
        out.willing_to_relocate = True
    return out


def _countries(places: list[Place], work: str) -> list[str]:
    return list(dict.fromkeys(p.country for p in places if p.work == work and p.country))


def synthesize_places(cfg: SearchConfig, home_country: str) -> SearchConfig:
    """Old configs have only `search.locations`: show them as places (nothing is saved).

    All become "ask": we cannot know where you may work, so no work right is assumed."""
    s = cfg.search
    if s.places:
        return cfg
    labels = [x for x in dict.fromkeys(s.locations) if x.strip() and x.strip().lower() != "remote"]
    if not labels:
        return cfg

    def iso(label: str) -> str:
        found = geo.country(label)
        return found.iso2 if found else iso2_of(label) or home_country.upper()

    places = [Place(label=x, country=iso(x), work="ask") for x in labels]
    remote = "remote" in cfg.filters.work_modes
    found = s.model_copy(update={"places": places, "remote": remote})
    return cfg.model_copy(update={"search": found})
