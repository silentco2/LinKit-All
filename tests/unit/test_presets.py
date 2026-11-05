"""Country/track source presets, Pace and Pickiness."""

import pytest
from jobspy.model import Country

from linkit_all.core.api_keys import KNOWN
from linkit_all.core.presets import (
    _COUNTRIES,
    _GENERAL_BY_COUNTRY,
    _GENERAL_GLOBAL,
    _TECH_BY_COUNTRY,
    _TECH_GLOBAL,
    PACE,
    PICKINESS,
    Track,
    country_preset,
    pace_of,
    pickiness_of,
    source_preset,
)
from linkit_all.core.search import (
    DEFAULT_TELEGRAM_CHANNELS,
    ApplySection,
    MatchingSection,
    SourcesSection,
)
from linkit_all.sources import registry

TRACKS: tuple[Track, ...] = ("tech", "general")


@pytest.mark.parametrize("text", ["Egypt", "egypt", "Cairo, Egypt", "Alexandria", "EG"])
def test_egypt_spellings(text: str) -> None:
    p = country_preset(text)
    assert (p.name, p.jobspy, p.currency, p.region) == ("Egypt", "egypt", "EGP", "egypt")


def test_gulf_mena_and_unknown() -> None:
    p = country_preset("Riyadh")
    assert (p.name, p.currency, p.region) == ("Saudi Arabia", "SAR", "gulf")
    assert country_preset("Dubai").currency == "AED"
    assert country_preset("Amman").jobspy == ""  # jobspy has no Jordan
    assert country_preset("Tunisia").region == "mena"
    u = country_preset("Atlantis")
    assert (u.name, u.jobspy, u.currency, u.region) == ("", "", "USD", "other")
    assert country_preset("") == u


def test_jobspy_keys_are_valid() -> None:
    for jobspy, _, _ in _COUNTRIES.values():
        assert not jobspy or Country.from_string(jobspy)


def test_source_presets() -> None:
    egypt = country_preset("Egypt")
    assert "wuzzuf" in source_preset(egypt, "general")["regional"]
    assert source_preset(country_preset("UAE"), "tech")["regional"] == ["bayt"]
    mena_tech = ["IT_jobs_coop", "Freejobs5", "findmyremote_frontend", "SDEjobsandinternships",
                 "ELIT_IT", "technomajed"]  # fmt: skip
    for name in ("Egypt", "Riyadh", "Jordan"):
        assert source_preset(country_preset(name), "tech")["telegram_channels"] == mena_tech
        assert source_preset(country_preset(name), "general")["telegram_channels"] == []
        assert SourcesSection(telegram_channels=mena_tech).telegram_channels == mena_tech
    other = country_preset("Berlin")
    assert source_preset(other, "tech")["telegram_channels"] == list(DEFAULT_TELEGRAM_CHANNELS)
    assert source_preset(other, "general")["telegram_channels"] == []
    assert "instaffo" in source_preset(other, "tech")["enabled"]
    assert "arbeitnow" in source_preset(other, "general")["enabled"]
    assert "instaffo" not in source_preset(egypt, "tech")["enabled"]
    assert "glassdoor" in source_preset(country_preset("Qatar"), "tech")["jobspy"]
    assert "glassdoor" not in source_preset(egypt, "tech")["jobspy"]
    assert "zip_recruiter" in source_preset(country_preset("USA"), "tech")["jobspy"]
    assert "zip_recruiter" not in source_preset(other, "tech")["jobspy"]


def test_source_presets_validate() -> None:
    for name in [*_COUNTRIES, "Atlantis"]:
        for track in TRACKS:
            SourcesSection(**source_preset(country_preset(name), track))  # type: ignore[arg-type]


def test_enabled_names_exist_and_are_keyless() -> None:
    found = registry(None, None)
    names = {*_TECH_GLOBAL, *_GENERAL_GLOBAL}
    for table in (_TECH_BY_COUNTRY, _GENERAL_BY_COUNTRY):
        names |= {n for v in table.values() for n in v}
    for n in names:
        assert n in found and found[n].kind in ("aggregator", "board", "company"), n
        assert n not in KNOWN, n  # keyed plugins are named after their provider


def test_pace_and_pickiness_roundtrip() -> None:
    for n, v in PACE.items():
        assert pace_of(ApplySection(**v)) == n
    for n, v in PICKINESS.items():
        assert pickiness_of(MatchingSection(**v)) == n
    assert pace_of(ApplySection()) == "balanced"
    assert pickiness_of(MatchingSection()) == "balanced"
    assert pace_of(ApplySection(max_per_run=7)) is None
    assert pickiness_of(MatchingSection(tier_high=10)) is None
