import json

import httpx

from linkit_all.sources.ats.darwinbox import Darwinbox
from linkit_all.sources.ats_detector import detect

BOARD = "northwind.darwinbox.in/main"


def test_search_posts_the_page_and_reads_annual_pay(search_pages, load_fixture):
    data = load_fixture("darwinbox/alljobs.json")
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert str(req.url) == (
            "https://northwind.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main"
        )
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=data)

    ((a, b),) = search_pages(Darwinbox(), handler, board=BOARD)
    assert bodies == [{"companyId": "main", "page": 1, "sort_option": "new", "limit": 50}]
    assert (a.title, a.company) == ("Backend & API Engineer", "Northwind")
    assert a.location == "Pune, India; Remote" and a.remote == "remote"
    assert a.url == "https://northwind.darwinbox.in/ms/candidatev2/main/careers/jobDetails/a1b2"
    assert a.description == "Build APIs." and a.posted_at is not None
    assert (a.salary_min, a.salary_max, a.salary_currency, a.salary_interval) == (
        1200000,
        1800000,
        "INR",
        "year",
    )
    assert b.location == "Mumbai" and b.salary_min is None  # monthly pay is not converted
    assert b.posted_at is not None and b.posted_at.isoformat() == "2026-08-01T00:00:00"


def test_url_patterns():
    url = "https://northwind.darwinbox.in/ms/candidatev2/main/careers/allJobs"
    assert detect(url) == ("darwinbox", BOARD)
    assert detect("https://darwinbox.com/") is None
