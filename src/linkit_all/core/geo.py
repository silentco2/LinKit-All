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


def _tier(names: Sequence[str], q: str) -> int | None:
    """0 exact, 1 prefix, 2 substring: the best any of the names reaches."""
    tiers = [0 if n == q else 1 if n.startswith(q) else 2 for n in names if n and q in n]
    return min(tiers, default=None)


def search_places(q: str, lang: str = "en", limit: int = 10) -> list[dict[str, str]]:
    """Cities and countries for `q`, matched on English and Arabic names alike: exact, then
    prefix, then substring; within a tier countries first, then by population. Both labels
    come back; `lang` only says which one the caller shows, so it does not change matching."""
    nq = _norm(q)
    if not nq:
        return []
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
