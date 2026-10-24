from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import peoplesoft
from linkit_all.sources.ats.peoplesoft import Row, count, parse_page, parse_posting
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "careers.dc.gov/erecruit/EMPLOYEE/HRMS"
COMPONENT = "/psc/erecruit/EMPLOYEE/HRMS/c/HRS_HRAM_FL.HRS_CG_SEARCH_FL.GBL"


def make_handler(
    load_fixture: Callable[[str], Any],
    posts: list[dict[str, str]] | None = None,
    postbacks: tuple[str, ...] = ("dc_postback.html",),
) -> Callable[[httpx.Request], httpx.Response]:
    queue = list(postbacks)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.url.host == "careers.dc.gov" and req.url.path == COMPONENT
        if req.method == "POST":
            form = dict(httpx.QueryParams(req.content.decode()))
            if posts is not None:
                posts.append(form)
            return httpx.Response(200, text=load_fixture(f"peoplesoft/{queue.pop(0)}"))
        if req.url.params["Page"] == "HRS_APP_SCHJOB_FL":
            return httpx.Response(200, text=load_fixture("peoplesoft/dc_search.html"))
        if req.url.params["JobOpeningId"] == "33704":
            return httpx.Response(200, text=load_fixture("peoplesoft/dc_posting.html"))
        return httpx.Response(500)  # the other postings' pages are not in the fixtures

    return handler


def test_page_reads_rows_count_and_form(load_fixture: Callable[[str], Any]) -> None:
    page = parse_page(load_fixture("peoplesoft/dc_search.html"))
    assert page.total == 3 and len(page.rows) == 2
    assert page.rows[0] == Row(
        "33704", "Fiscal Monitor (SOR)", "64 New York Ave. N.E.", "10/14/2026"
    )
    assert page.fields["ICSID"] and page.fields["ICStateNum"] == "1"
    assert page.action == f"https://careers.dc.gov{COMPONENT}"
    with pytest.raises(ValueError, match="no win0 form"):
        parse_page("Site name is not valid. Check your url syntax and try again.")


def test_count_formats() -> None:
    for text, want in {
        "68 rows": 68,
        "1 of 96": 96,
        "Ligne 1 sur 96": 96,
        "1,234 rows": 1234,
    }.items():
        assert count(text) == want
    assert count("No jobs found.") is None


def test_posting_sections_in_order(load_fixture: Callable[[str], Any]) -> None:
    html = load_fixture("peoplesoft/sandia_posting.html")
    title, location, description, schedule = parse_posting(  # type: ignore[misc]
        html, Row("698789", "", "Albuquerque, NM", "10/14/2026")
    )
    about = description.index("About Sandia")
    duty = description.index("What Your Job Will Be Like")
    assert about < duty < description.index("Salary Range")
    assert title.startswith("Cleared Senior/Principal Mechanical Engineer")
    assert location == "Albuquerque, NM" and schedule.lower().startswith("full")
    # another opening's page, or the search page an expired opening lands on, is not it
    assert parse_posting(html, Row("1", "", "", "")) is None
    assert (
        parse_posting(load_fixture("peoplesoft/dc_search.html"), Row("33704", "", "", "")) is None
    )


def test_posts_back_to_the_stated_count(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    posts: list[dict[str, str]] = []
    pages = search_pages(peoplesoft.PeopleSoft(), make_handler(load_fixture, posts), board=BOARD)
    assert len(posts) == 1
    assert posts[0]["ICAction"] == peoplesoft.LOAD_MORE and posts[0]["ICStateNum"] == "1"
    assert posts[0]["ICSID"]  # the form's session fields travel with the postback
    (job,) = pages[0]  # the other two postings could not be read and are left for the next run
    assert job.title == "Fiscal Monitor (SOR)" and job.company == "Dc"
    assert job.url.endswith("JobOpeningId=33704&PostingSeq=1") and job.ats == "peoplesoft"
    assert job.location == "64 New York Ave. N.E." and "JOB SUMMARY" in job.description
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-10-14"
    assert job.extra["id"] == "33704" and job.extra["board"] == BOARD


def test_walks_that_stall_or_read_nothing_fail(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    stalled = make_handler(load_fixture, postbacks=("dc_search.html",))
    with pytest.raises(ValueError, match="added no row"):
        search_pages(peoplesoft.PeopleSoft(), stalled, board=BOARD)

    inner = make_handler(load_fixture)

    def no_pages(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.params.get("JobOpeningId"):
            return httpx.Response(404)
        return inner(req)

    with pytest.raises(ValueError, match="read none"):
        search_pages(peoplesoft.PeopleSoft(), no_pages, board=BOARD)


def test_form_must_post_to_the_boards_host(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    html = load_fixture("peoplesoft/dc_search.html").replace(
        "https://careers.dc.gov/psc", "https://evil.example/psc"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=html)

    with pytest.raises(ValueError, match=r"not to careers.dc.gov"):
        search_pages(peoplesoft.PeopleSoft(), handler, board=BOARD)


def test_resume_and_bad_board(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peoplesoft, "CHUNK", 1)
    pages = search_pages(
        peoplesoft.PeopleSoft(), make_handler(load_fixture), board=BOARD, start_page=1
    )
    assert [len(p) for p in pages] == [0, 0]  # postings 2 and 3 are not readable
    with pytest.raises(ValueError, match="<host>/<site>/<portal>/<node>"):
        search_pages(peoplesoft.PeopleSoft(), lambda r: httpx.Response(200), board="careers.dc.gov")
    assert detect(f"peoplesoft:{BOARD}") == ("peoplesoft", BOARD)
