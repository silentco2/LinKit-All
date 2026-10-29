"""Country and track defaults for sources, plus the Pace and Pickiness presets. Pure data."""

from dataclasses import dataclass
from typing import Literal

from linkit_all.apply.answers import canonical_country
from linkit_all.core.search import DEFAULT_TELEGRAM_CHANNELS, ApplySection, MatchingSection

Track = Literal["tech", "general"]
Region = Literal["egypt", "gulf", "mena", "other"]
PaceName = Literal["careful", "balanced", "fast"]
PickinessName = Literal["strict", "balanced", "wide"]


@dataclass(frozen=True)
class CountryPreset:
    name: str  # as the answer engine knows it, title-cased ("Egypt"); "" when unknown
    jobspy: str  # python-jobspy country key; "" when jobspy has none
    currency: str  # ISO 4217
    region: Region


# canonical country (answers.canonical_country) -> (jobspy key, currency, region)
_COUNTRIES: dict[str, tuple[str, str, Region]] = {
    "egypt": ("egypt", "EGP", "egypt"),
    "saudi arabia": ("saudi arabia", "SAR", "gulf"),
    "united arab emirates": ("united arab emirates", "AED", "gulf"),
    "qatar": ("qatar", "QAR", "gulf"),
    "kuwait": ("kuwait", "KWD", "gulf"),
    "bahrain": ("bahrain", "BHD", "gulf"),
    "oman": ("oman", "OMR", "gulf"),
    "jordan": ("", "JOD", "mena"),
    "lebanon": ("", "LBP", "mena"),
    "morocco": ("morocco", "MAD", "mena"),
    "tunisia": ("", "TND", "mena"),
    "algeria": ("", "DZD", "mena"),
    "iraq": ("", "IQD", "mena"),
    "palestine": ("", "ILS", "mena"),
    "united states": ("usa", "USD", "other"),
    "united kingdom": ("uk", "GBP", "other"),
    "canada": ("canada", "CAD", "other"),
    "ireland": ("ireland", "EUR", "other"),
    "germany": ("germany", "EUR", "other"),
    "netherlands": ("netherlands", "EUR", "other"),
    "france": ("france", "EUR", "other"),
    "spain": ("spain", "EUR", "other"),
    "india": ("india", "INR", "other"),
    "pakistan": ("pakistan", "PKR", "other"),
    "singapore": ("singapore", "SGD", "other"),
    "australia": ("australia", "AUD", "other"),
    "japan": ("japan", "JPY", "other"),
}  # fmt: skip

_UNKNOWN = CountryPreset("", "", "USD", "other")


def country_preset(country: str) -> CountryPreset:
    """Any spelling the answer engine understands: "Egypt", "Cairo, Egypt", "ksa", "Riyadh"."""
    key = canonical_country(country)
    if key not in _COUNTRIES:
        return _UNKNOWN
    jobspy, currency, region = _COUNTRIES[key]
    return CountryPreset(key.title(), jobspy, currency, region)


# Opt-in aggregator / board plugins, by hand: the plugins carry no region or track. Keyless only.
_TECH_GLOBAL = [
    "remoteok", "remotive", "himalayas", "jobicy", "workingnomads", "weworkremotely", "nodesk",
    "jobspresso", "remotedotcom", "hackernews", "builtin", "pythonorg", "workablemarketplace",
]  # fmt: skip
_GENERAL_GLOBAL = ["workablemarketplace"]
_TECH_BY_COUNTRY = {
    "germany": ["instaffo"],
    "spain": ["getmanfred", "joppy"],
    "japan": ["japandev"],
}
_GENERAL_BY_COUNTRY = {
    "germany": ["arbeitnow", "arbeitsagentur"],
    "singapore": ["mycareersfuture"],
    "australia": ["seek"],
    "united states": ["themuse"],
    "france": ["wttj"],
}
_REGIONAL: dict[Region, list[str]] = {
    "egypt": ["wuzzuf", "forasna", "bayt"],
    "gulf": ["bayt"],
    "mena": ["bayt"],
    "other": [],
}


def source_preset(country: CountryPreset, track: Track) -> dict[str, list[str]]:
    """Values for SourcesSection's jobspy, regional, enabled and telegram_channels."""
    jobspy = ["linkedin", "indeed", "google"]
    if country.region in ("gulf", "other"):
        jobspy.append("glassdoor")
    if country.name in ("United States", "Canada"):
        jobspy.append("zip_recruiter")
    by_country = _TECH_BY_COUNTRY if track == "tech" else _GENERAL_BY_COUNTRY
    enabled = [
        *(_TECH_GLOBAL if track == "tech" else _GENERAL_GLOBAL),
        *by_country.get(country.name.lower(), []),
    ]
    # ponytail: MENA channel lists are curated later by the maintainer; none ship for now.
    tech_other = track == "tech" and country.region == "other"
    channels = list(DEFAULT_TELEGRAM_CHANNELS) if tech_other else []
    return {
        "jobspy": jobspy,
        "regional": list(_REGIONAL[country.region]),
        "enabled": enabled,
        "telegram_channels": channels,
    }


# ApplySection / MatchingSection fields. "balanced" equals the section defaults.
PACE: dict[PaceName, dict[str, int]] = {
    "careful": {
        "parallel_sites": 1, "min_pause_s": 60, "max_pause_s": 120,
        "daily_cap_per_site": 10, "max_per_run": 5,
    },
    "balanced": {
        "parallel_sites": 3, "min_pause_s": 20, "max_pause_s": 60,
        "daily_cap_per_site": 20, "max_per_run": 10,
    },
    "fast": {
        "parallel_sites": 3, "min_pause_s": 10, "max_pause_s": 30,
        "daily_cap_per_site": 40, "max_per_run": 25,
    },
}  # fmt: skip
PICKINESS: dict[PickinessName, dict[str, int]] = {
    "strict": {"tier_high": 9, "tier_mid": 6},
    "balanced": {"tier_high": 8, "tier_mid": 5},
    "wide": {"tier_high": 7, "tier_mid": 4},
}


def pace_of(apply: ApplySection) -> PaceName | None:
    """The preset the section matches exactly, else None (custom)."""
    return next((n for n, v in PACE.items() if _matches(apply, v)), None)


def pickiness_of(matching: MatchingSection) -> PickinessName | None:
    return next((n for n, v in PICKINESS.items() if _matches(matching, v)), None)


def _matches(section: ApplySection | MatchingSection, values: dict[str, int]) -> bool:
    return all(getattr(section, k) == x for k, x in values.items())
