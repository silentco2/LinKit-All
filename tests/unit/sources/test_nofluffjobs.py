import time

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.nofluffjobs import NoFluffJobs
from linkit_all.sources.base import JobStub


def _ok(data):
    return lambda req: httpx.Response(200, json=data)


def _place(city, code="", country=""):
    place = {"city": city}
    if code:
        place["country"] = {"code": code, "name": country}
    return place


def _row(id_, title, places, *, remote=False, posted=None, name="Acme", salary=None):
    return {
        "id": id_,
        "url": id_.lower(),
        "name": name,
        "title": title,
        "posted": posted or int(time.time() * 1000),
        "location": {"places": places, "fullyRemote": remote},
        **({"salary": salary} if salary else {}),
    }


LISTING = {
    "postings": [
        _row(
            "gcp-verita-Krakow",
            "GCP Data ETL",
            [_place("Kraków", "POL", "Poland")],
            name="Verita HR",
        ),
        _row(
            "remote-in-poland",
            "AI Engineer",
            [
                _place("Remote"),
                _place("Warsaw", "POL", "Poland"),
                _place("Budapest", "HUN", "Hungary"),
            ],
            remote=True,
            salary={
                "from": 100,
                "to": 120,
                "currency": "PLN",
                "period": "Hour",
                "containsSalary": "VISIBLE",
            },
        ),
        _row("remote-only", "Backend Dev", [_place("Remote")], remote=True),
        _row("no-company", "X", [], name=""),
    ]
}


def test_search_maps_the_listing_and_drops_unusable_rows(search_pages):
    ((verita, poland, remote),) = search_pages(NoFluffJobs(), _ok(LISTING))
    # newest first on equal dates keeps the order; check by id
    stubs = {s.extra["id"]: s for s in (verita, poland, remote)}
    v = stubs["gcp-verita-Krakow"]
    assert (v.title, v.company, v.location) == ("GCP Data ETL", "Verita HR", "Kraków, Poland")
    assert v.url == "https://nofluffjobs.com/job/gcp-verita-krakow" and v.remote is None
    assert v.extra == {"id": "gcp-verita-Krakow", "slug": "gcp-verita-krakow"}
    assert v.posted_at is not None and v.posted_at.year >= 2026
    # the "Remote" pseudo-place is skipped, so the real office and the salary survive
    p = stubs["remote-in-poland"]
    assert (p.location, p.remote) == ("Warsaw, Poland", "remote")
    assert (p.salary_min, p.salary_max, p.salary_currency, p.salary_interval) == (
        100,
        120,
        "PLN",
        "hour",
    )
    assert stubs["remote-only"].location == "Remote"
    assert "no-company" not in stubs


def test_old_postings_are_dropped_and_the_newest_come_first_up_to_the_limit(search_pages):
    now = int(time.time() * 1000)
    day = 86_400_000
    rows = [
        _row("old", "Old", [_place("Gdansk", "POL", "Poland")], posted=now - 400 * day),
        _row("mid", "Mid", [_place("Gdansk", "POL", "Poland")], posted=now - 3 * day),
        _row("new", "New", [_place("Gdansk", "POL", "Poland")], posted=now - day),
    ]
    pages = search_pages(NoFluffJobs(), _ok({"postings": rows}), limit=2)
    assert [s.extra["id"] for s in pages[0]] == ["new", "mid"]
    assert [s.extra["id"] for s in search_pages(NoFluffJobs(), _ok({"postings": rows}))[0]] == [
        "new",
        "mid",
    ]  # the default 14-day window drops "old"


def test_pages_of_100_and_resume(search_pages):
    rows = [_row(f"id{i}", f"T{i}", [_place("Gdansk", "POL", "Poland")]) for i in range(250)]
    handler = _ok({"postings": rows})
    assert [len(p) for p in search_pages(NoFluffJobs(), handler, limit=1000)] == [100, 100, 50]
    assert [len(p) for p in search_pages(NoFluffJobs(), handler, limit=1000, start_page=2)] == [50]


def test_fetch_details_joins_the_offer_and_the_requirements(fetch_details, load_fixture):
    detail = load_fixture("nofluffjobs/detail.json")
    stub = JobStub(
        source="nofluffjobs",
        url="https://nofluffjobs.com/job/project-support-consulting-specialist-itfs-remote",
        title="Project Support",
        company="ITFS",
    )
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=detail)

    out = fetch_details(NoFluffJobs(), handler, stub)
    assert seen == ["/api/posting/project-support-consulting-specialist-itfs-remote"]
    assert (
        "STANOWISKO" in out.description and "C1" in out.description and "<" not in out.description
    )


def test_it_is_an_opt_in_aggregator_with_one_feed_task():
    source = registry()["nofluffjobs"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a", "b"]}, "sources": {"enabled": ["nofluffjobs"]}}
    )
    assert len(source.tasks(cfg)) == 1
