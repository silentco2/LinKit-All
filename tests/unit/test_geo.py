"""Bundled offline lists: datasets, country lookup, place and title suggestions."""

import json
from typing import Any

import pytest

from linkit_all.core import geo

ARAB_LEAGUE = {
    "DZ", "BH", "KM", "DJ", "EG", "IQ", "JO", "KW", "LB", "LY", "MR",
    "MA", "OM", "PS", "QA", "SA", "SO", "SD", "SY", "TN", "AE", "YE",
}  # fmt: skip


def data(name: str) -> Any:
    return json.loads((geo.DATA / name).read_text("utf-8"))


def test_dataset_sizes_and_rows() -> None:
    sizes = {n: (geo.DATA / n).stat().st_size for n in ("cities.json", "titles.json", "fx.json")}
    assert sizes["cities.json"] < 2_000_000 and sizes["titles.json"] < 1_500_000
    cities, titles = data("cities.json"), data("titles.json")
    assert isinstance(cities, list) and len(cities) > 20_000
    assert cities == sorted(cities, key=lambda c: -c["p"])
    assert {"n", "ar", "c", "p"} == set(cities[0])
    assert isinstance(titles, list) and len(titles) > 20_000
    assert len(geo.countries()) > 200


def test_every_arab_league_country_and_its_cities_are_kept() -> None:
    by_iso = {c.iso2: c for c in geo.countries()}
    assert all(by_iso[iso].name_ar for iso in ARAB_LEAGUE)
    cities = data("cities.json")
    assert {c["c"] for c in cities if c["c"] in ARAB_LEAGUE} == ARAB_LEAGUE
    assert sum(c["c"] in ARAB_LEAGUE for c in cities) > 1000


def test_country_fields() -> None:
    egypt = geo.country("EG")
    assert egypt == geo.Country("EG", "Egypt", "مصر", "20", "EGP", "egypt")
    us = geo.country("us")
    assert us and (us.phone, us.currency, us.jobspy) == ("1", "USD", "usa")


@pytest.mark.parametrize(
    ("text", "iso"),
    [("EG", "EG"), ("egypt", "EG"), ("  Egypt ", "EG"), ("مصر", "EG"), ("الإمارات", "AE"),
     ("UAE", "AE"), ("KSA", "SA"), ("UK", "GB"), ("U.S.A.", "US"), ("USA", "US"),
     ("Saudi Arabia", "SA"), ("السعودية", "SA"), ("Cairo, Egypt", "EG"), ("القاهرة، مصر", "EG"),
     ("Dubai, UAE", "AE"), ("Berlin, Germany", "DE")],
)  # fmt: skip
def test_country_lookup(text: str, iso: str) -> None:
    found = geo.country(text)
    assert found is not None and found.iso2 == iso


@pytest.mark.parametrize("text", ["", "Atlantis", "Cairo", "Nowhere, Atlantis"])
def test_country_lookup_misses(text: str) -> None:
    assert geo.country(text) is None


def test_places_arabic_query_finds_cairo() -> None:
    first = geo.search_places("القاهرة", "ar")[0]
    assert (first["label"], first["iso2"], first["kind"]) == ("Cairo, Egypt", "EG", "city")
    assert first["label_ar"] == "القاهرة، مصر"
    assert first["city"] == "Cairo" and first["country"] == "Egypt"


def test_places_english_prefix_and_ranking() -> None:
    labels = [p["label"] for p in geo.search_places("cairo", limit=5)]
    assert labels[0] == "Cairo, Egypt"
    # prefix matches (Cairo...) come before substring matches (New Cairo)
    wide = [p["label"] for p in geo.search_places("cairo", limit=50)]
    prefix = [i for i, label in enumerate(wide) if label.lower().startswith("cairo")]
    other = [i for i, label in enumerate(wide) if not label.lower().startswith("cairo")]
    assert not other or max(prefix) < min(other)


def test_places_countries_first_on_exact_match_and_population_after() -> None:
    first = geo.search_places("egypt")[0]
    assert (first["kind"], first["label"], first["city"]) == ("country", "Egypt", "")
    assert geo.search_places("singapore")[0]["kind"] == "country"  # also a city
    pops = {(c["n"], c["c"]): c["p"] for c in data("cities.json")}
    big = [p for p in geo.search_places("san", limit=30) if p["kind"] == "city"]
    sizes = [pops[(p["city"], p["iso2"])] for p in big if p["label"].lower().startswith("san ")]
    assert sizes == sorted(sizes, reverse=True)


def test_places_aliases_accents_and_limits() -> None:
    assert geo.search_places("") == [] and geo.search_places("   ") == []
    assert geo.search_places("zzzzqq") == []
    assert len(geo.search_places("a", limit=3)) == 3
    assert geo.search_places("aswan")[0]["iso2"] == "EG"  # stored as "Aswān"
    country_only = geo.search_places("مصر")[0]
    assert (country_only["kind"], country_only["label_ar"]) == ("country", "مصر")


def test_titles_prefix_before_substring_and_limit() -> None:
    got = geo.search_titles("software dev", limit=5)
    assert len(got) == 5 and all(t.lower().startswith("software dev") for t in got)
    mixed = geo.search_titles("developer", limit=200)
    assert mixed[0].lower().startswith("developer") and "Software Developer" in mixed
    assert geo.search_titles("zzzzqq") == []


def test_titles_extra_first_deduped_and_filtered() -> None:
    extra = ["Backend Engineer", "Chef", "backend engineer", "Lead Backend Engineer (Remote)"]
    got = geo.search_titles("backend", limit=10, extra=extra)
    assert got[:2] == ["Backend Engineer", "Lead Backend Engineer (Remote)"]
    assert "Chef" not in got
    assert len({t.casefold() for t in got}) == len(got)
    assert geo.search_titles("engineer", limit=3, extra=["Zeta Engineer"])[0] == "Zeta Engineer"
