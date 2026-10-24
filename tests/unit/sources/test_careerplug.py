import httpx

from linkit_all.sources.ats.careerplug import CareerPlug, job_links
from linkit_all.sources.ats_detector import detect

BASE = "https://acme.careerplug.com/"


def router(load_fixture, calls: list[str] | None = None):
    pages = {
        ("/jobs", ""): "careerplug/list1.html",
        ("/jobs", "2"): "careerplug/list2.html",
        ("/jobs", "3"): "careerplug/list2.html",  # a board clamps ?page=N to its last page
        ("/jobs/100", ""): "careerplug/detail_100.html",
        ("/jobs/200", ""): "careerplug/detail_200.html",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if calls is not None:
            calls.append(str(req.url))
        name = pages.get((req.url.path, req.url.params.get("page", "")))
        return httpx.Response(200, text=load_fixture(name)) if name else httpx.Response(404)

    return handler


def test_job_links_dedupe(load_fixture):
    assert job_links(load_fixture("careerplug/list1.html"), BASE) == [BASE + "jobs/100"]


def test_search_pages_until_nothing_new(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(CareerPlug(), router(load_fixture, calls), board="acme", calls=None)
    a, b = (p[0] for p in pages)
    assert [len(p) for p in pages] == [1, 1]
    assert a.title == "Restaurant Team Member"
    assert a.company == "Golden Corral - Concord"
    assert a.location == "Concord, CA, US"
    assert a.url == BASE + "jobs/100" and a.extra == {"board": "acme", "id": "100"}
    assert "Serve guests." in a.description
    assert b.company == "Golden Corral - Reno" and b.extra["id"] == "200"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-20T12:00:00"


def test_resume_starts_at_the_given_page(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(
        CareerPlug(), router(load_fixture), board="acme", start_page=1, calls=calls
    )
    assert [p[0].extra["id"] for p in pages] == ["200"]
    assert "https://acme.careerplug.com/jobs?page=2" in calls
    assert "https://acme.careerplug.com/jobs" not in calls


def test_url_patterns():
    assert detect("https://acme.careerplug.com/jobs/100", [CareerPlug()]) == ("careerplug", "acme")
