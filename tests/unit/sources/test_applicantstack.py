import httpx
import pytest

from linkit_all.sources.ats.applicantstack import ApplicantStack
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.careers import Unsupported


def router(load_fixture, pages: dict[str, str], calls: list[str] | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if calls is not None:
            calls.append(str(req.url))
        page = req.url.params.get("pge", "1")
        return httpx.Response(200, text=load_fixture(pages[page]))

    return handler


def test_search_walks_every_listing_page(search_pages, load_fixture):
    calls: list[str] = []
    handler = router(
        load_fixture,
        {"1": "applicantstack/openings_p1.html", "2": "applicantstack/openings_p2.html"},
        calls,
    )
    pages = search_pages(ApplicantStack(), handler, board="OzarkHealth")
    # the fixture's pager says "of 3" at 2 rows a page; the walk ends once page * 100 >= total
    stubs = [s for p in pages for s in p]
    assert [s.title for s in stubs[:2]] == ["CLINIC FRONT OFFICE RECEPTIONIST", "CLINIC LPN"]
    assert stubs[0].url == "https://ozarkhealth.applicantstack.com/x/detail/a23rqqeo6x57"
    assert stubs[0].location == "Clinton, AR"
    assert stubs[0].extra["id"] == "a23rqqeo6x57" and stubs[0].ats == "applicantstack"
    assert len(calls) == 1  # 3 rows <= 100 per page: one request is the whole board


def test_paging_and_resume(search_pages, load_fixture):
    p1 = load_fixture("applicantstack/openings_p1.html").replace("of 3", "of 101")
    p2 = load_fixture("applicantstack/openings_p2.html")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=p2 if req.url.params.get("pge") == "2" else p1)

    pages = search_pages(ApplicantStack(), handler, board="ozarkhealth")
    assert [len(p) for p in pages] == [2, 1]
    calls: list[str] = []
    resumed = search_pages(
        ApplicantStack(), handler, board="ozarkhealth", start_page=1, calls=calls
    )
    assert [len(p) for p in resumed] == [1]
    pages_asked = [c for c in calls if "robots" not in c]
    assert pages_asked == ["https://ozarkhealth.applicantstack.com/x/openings?pge=2"]


def test_empty_board_is_empty(search_pages, load_fixture):
    handler = router(load_fixture, {"1": "applicantstack/openings_empty.html"})
    assert search_pages(ApplicantStack(), handler, board="sunbelt") == []


def test_page_without_the_table_is_not_a_listing(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>Invalid page number</body></html>")

    with pytest.raises(Unsupported):
        search_pages(ApplicantStack(), handler, board="gone")


def test_robots_disallow_is_respected(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /x/\n")
        raise AssertionError("must not fetch")

    with pytest.raises(Unsupported):
        search_pages(ApplicantStack(), handler, board="ozarkhealth")


def test_fetch_details_reads_jobposting_but_keeps_the_row_title(fetch_details, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("applicantstack/detail.html"))

    stub = ApplicantStack().parse_listing(
        load_fixture("applicantstack/openings_p1.html"), "ozarkhealth", "Ozark Health"
    )[0][0]
    stub = stub.model_copy(update={"title": "EMERGENCY ROOM RN", "location": ""})
    out = fetch_details(ApplicantStack(), handler, stub)
    assert out.title == "EMERGENCY ROOM RN"
    assert "Proof of the legal right to work" in out.description
    assert out.posted_at is not None and out.posted_at.year == 2026
    assert out.location  # filled from the JobPosting address


def test_url_patterns():
    assert detect("https://m30.applicantstack.com/x/openings", [ApplicantStack()]) == (
        "applicantstack",
        "m30",
    )
