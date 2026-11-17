import httpx

from linkit_all.sources.ats.hirehive import HireHive
from linkit_all.sources.ats_detector import detect


def test_search(search_pages, load_fixture):
    data = load_fixture("hirehive/jobs.json")
    calls: list[str] = []
    ((a, b),) = search_pages(
        HireHive(), lambda req: httpx.Response(200, json=data), board="northwind", calls=calls
    )
    assert calls == ["https://northwind.hirehive.com/api/v2/jobs?page=1&page_size=100"]
    assert (a.title, a.company, a.location) == ("Support Agent", "Northwind", "Cork, Ireland")
    assert a.description == "Help customers." and a.extra["id"] == "j1"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-05T09:00:00"
    # the hidden "none" tier is never read; the shown yearly range is
    assert (a.salary_min, a.salary_max, a.salary_currency, a.salary_interval) == (
        40000,
        50000,
        "EUR",
        "year",
    )
    assert b.url == "https://sister.hirehive.com/group-role-y2"  # a sister tenant's posting
    assert b.location == "Remote, Ireland" and b.remote == "remote"
    assert b.description == "Plain body." and b.salary_min is None  # hourly pay is left out


def test_url_patterns():
    assert detect("https://northwind.hirehive.com/job/12/x") == ("hirehive", "northwind")
    assert detect("https://app.hirehive.com/login") is None
