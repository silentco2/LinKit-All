"""Offline place, country and job-title suggestions from the lists in `data/` (no lookups)."""

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from linkit_all.apply.answers import canonical_country

DATA = Path(__file__).parent.parent / "data"


@dataclass(frozen=True)
class Country:
    iso2: str
    name: str
    name_ar: str  # "" when we have no checked Arabic name
    phone: str  # calling code without "+"
    currency: str
    jobspy: str  # python-jobspy country key, "" when jobspy has none


def _json(name: str) -> Any:
    return json.loads((DATA / name).read_text("utf-8"))


@lru_cache(maxsize=1)
def _countries() -> tuple[Country, ...]:
    return tuple(Country(**c) for c in _json("countries.json"))


def countries() -> list[Country]:
    return list(_countries())


_AR_FOLD = str.maketrans({"ى": "ي", "ة": "ه", "ـ": None})  # noqa: RUF001
_ALIASES = {
    "uae": "AE", "emirates": "AE", "ksa": "SA", "uk": "GB", "great britain": "GB",
    "britain": "GB", "england": "GB", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "america": "US", "korea": "KR", "russia": "RU", "czech republic": "CZ",
    "palestinian territory": "PS", "الإمارات العربية المتحدة": "AE",
    "المملكة العربية السعودية": "SA", "السعودية العربية": "SA",
}  # fmt: skip


def _norm(text: str) -> str:
    """Casefolded, accents and Arabic marks removed, alef forms and teh marbuta folded,
    punctuation turned into spaces: how both the query and the stored names are compared."""
    s = unicodedata.normalize("NFKD", text.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c)).translate(_AR_FOLD)
    return " ".join(re.sub(r"[\W_]+", " ", s).split())


@lru_cache(maxsize=1)
def _by_key() -> dict[str, Country]:
    keys: dict[str, Country] = {}
    for c in _countries():
        for k in (c.iso2, c.name, c.name_ar):
            if k:
                keys.setdefault(_norm(k), c)
    by_iso = {c.iso2: c for c in _countries()}
    for alias, iso in _ALIASES.items():
        keys.setdefault(_norm(alias), by_iso[iso])
    return keys


def country(code_or_name: str) -> Country | None:
    """By ISO2, English name, Arabic name or alias (UAE, KSA, UK, USA). A place such as
    "Cairo, Egypt" also works: its last part is tried, then the answer engine's aliases."""
    keys = _by_key()
    if hit := keys.get(_norm(code_or_name)):
        return hit
    if re.search("[,،]", code_or_name):
        tail = re.split("[,،]", code_or_name)[-1]
        return keys.get(_norm(tail)) or keys.get(_norm(canonical_country(code_or_name)))
    return None


@dataclass(frozen=True)
class _Place:
    en: str  # normalized English name
    ar: str  # normalized Arabic name, "" when none
    city: str
    city_ar: str
    country: Country
    pop: int  # 0 for a country row
    kind: str  # "city" | "country"


@lru_cache(maxsize=1)
def _places() -> tuple[_Place, ...]:
    by_iso = {c.iso2: c for c in _countries()}
    out = [_Place(_norm(c.name), _norm(c.name_ar), "", "", c, 0, "country") for c in _countries()]
    seen: set[tuple[str, str]] = set()
    for r in _json("cities.json"):  # sorted by population: the bigger twin is kept
        if (c := by_iso.get(r["c"])) is None or (r["n"], r["c"]) in seen:
            continue
        seen.add((r["n"], r["c"]))
        out.append(_Place(_norm(r["n"]), _norm(r["ar"]), r["n"], r["ar"], c, r["p"], "city"))
    return tuple(out)


@lru_cache(maxsize=1024)
def arabic_name(name: str) -> str:
    """The (normalized) Arabic name of a city or country given in English; '' when unknown."""
    key = _norm(name)
    return next((p.ar for p in _places() if p.en == key and p.ar), "")


def _tier(names: Sequence[str], q: str) -> int | None:
    """0 exact, 1 prefix, 2 substring: the best any of the names reaches."""
    tiers = [0 if n == q else 1 if n.startswith(q) else 2 for n in names if n and q in n]
    return min(tiers, default=None)


def _city(name: str, iso2: str = "") -> _Place | None:
    """The biggest city called `name`, in that country when one is given."""
    key = _norm(name)
    if not key:
        return None
    return next(
        (
            p
            for p in _places()
            if p.kind == "city" and key in (p.en, p.ar) and (not iso2 or p.country.iso2 == iso2)
        ),
        None,
    )


_SEPARATOR = re.compile(r"[,،/–—]|\s-+|-+\s")  # noqa: RUF001
_US_STATES = frozenset(
    [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    ]
)


def _hyphen_parts(part: str) -> list[str]:
    """ "Cairo-Egypt" is two places; "Winston-Salem" and "Al-Mansoura" are one."""
    tail_parts: list[str] = []
    while "-" in part and not _city(part):
        head, _, tail = part.rpartition("-")
        if len(head.strip()) < 3 or not (_city(tail) or _norm(tail) in _by_key()):
            break
        tail_parts.insert(0, tail.strip())
        part = head.strip()
    return [part, *tail_parts]


def _country_part(part: str, others: list[str]) -> Country | None:
    found = _by_key().get(_norm(part))
    if found and part.upper() in _US_STATES and not any(_city(o, found.iso2) for o in others):
        return None  # "Denver, CO" is Colorado; "Bogota, CO" is Colombia
    return found


def typed_place(text: str) -> dict[str, str] | None:
    """A place typed in parts: "City, State, Country", in that order or country first, the
    parts separated by a comma, slash or dash. A row like `search_places`' with the city and
    state in English where the bundled list knows them; other names stay as typed. None when
    the text is a single name. A country left out is taken from the city or state."""
    parts = [
        p for raw in _SEPARATOR.split(text) if (x := raw.strip(" -")) for p in _hyphen_parts(x)
    ]
    if len(parts) < 2:
        return None
    place = _country_part(parts[-1], parts[:-1])
    if place is None and (place := _country_part(parts[0], parts[1:])):
        parts.reverse()
    if place is None:  # still being typed: "Cairo, Eg"
        near = next((c.country for x in reversed(parts[:-1]) if (c := _city(x))), None)
        typed = _norm(parts[-1])
        if (
            near
            and typed
            and (_norm(near.name).startswith(typed) or _norm(near.name_ar).startswith(typed))
        ):
            place = near
    rest = parts[:-1] if place else parts
    city, state = rest[-2:] if len(rest) > 1 else (rest[0], "")
    if place is None and state.upper() in _US_STATES:
        place = country("US")
    if place is None and (known := _city(state) or _city(city)):
        place = known.country
    iso2 = place.iso2 if place else ""
    found = _city(city, iso2), _city(state, iso2)
    en = [p.city if p else x for p, x in zip(found, (city, state), strict=True)]
    ar = [(p.city_ar or p.city) if p else x for p, x in zip(found, (city, state), strict=True)]
    return {
        "label": ", ".join(x for x in (*en, place.name if place else "") if x),
        "label_ar": "، ".join(
            x for x in (*ar, (place.name_ar or place.name) if place else "") if x
        ),
        "city": en[0],
        "state": en[1],
        "country": place.name if place else "",
        "iso2": iso2,
        "kind": "typed",
    }


def search_places(q: str, lang: str = "en", limit: int = 10) -> list[dict[str, str]]:
    """Cities and countries for `q`, matched on English and Arabic names alike: exact, then
    prefix, then substring; within a tier countries first, then by population. Both labels
    come back; `lang` only says which one the caller shows, so it does not change matching.
    Text in several parts ("Maadi / Cairo / Egypt") comes back as that one place."""
    nq = _norm(q)
    if not nq:
        return []
    if (typed := typed_place(q)) is not None:
        return [typed]
    hits = []
    for p in _places():
        if (tier := _tier((p.en, p.ar), nq)) is not None:
            hits.append((tier, p.kind != "country", -p.pop, p))
    hits.sort(key=lambda h: h[:3])
    out = []
    for *_, p in hits[:limit]:
        c = p.country
        if p.kind == "country":
            label, label_ar = c.name, c.name_ar or c.name
        else:
            label = f"{p.city}, {c.name}"
            label_ar = f"{p.city_ar or p.city}، {c.name_ar or c.name}"
        out.append({"label": label, "label_ar": label_ar, "city": p.city, "country": c.name,
                    "iso2": c.iso2, "kind": p.kind})  # fmt: skip
    return out


@lru_cache(maxsize=1)
def _titles() -> tuple[tuple[str, str], ...]:
    return tuple((t, t.casefold()) for t in _json("titles.json"))


def search_titles(q: str, limit: int = 10, extra: Sequence[str] = ()) -> list[str]:
    """Job titles containing `q`. `extra` (from the CV and found jobs) come first when they
    match; within each list prefix matches come before substring matches."""
    nq = " ".join(q.casefold().split())
    lists = [[(t, t.casefold()) for t in extra if t.strip()], _titles()]
    out: list[str] = []
    seen: set[str] = set()
    for pool in lists:
        for starts in (True, False):
            for title, low in pool:
                if low in seen or not (low.startswith(nq) if starts else nq in low):
                    continue
                seen.add(low)
                out.append(title.strip())
                if len(out) >= limit:
                    return out
    return out
