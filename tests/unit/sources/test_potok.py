import httpx
import pytest

from linkit_all.sources.ats.potok import Potok
from linkit_all.sources.ats_detector import detect


def _serve(**pages: str):
    def handler(req: httpx.Request) -> httpx.Response:
        text = pages.get(req.url.path)
        return httpx.Response(404) if text is None else httpx.Response(200, text=text)

    return handler


def test_search_reads_every_posting(search_pages, load_fixture):
    handler = _serve(**{"/open/jobs/": load_fixture("potok/list.html")})
    pages = search_pages(Potok(), handler, board="skyengteam")
    assert len(pages) == 1 and len(pages[0]) == 16
    job = next(s for s in pages[0] if s.extra["id"] == "2747")
    assert job.title == "Senior Full Stack Developer (PHP, Angular)"
    assert job.location == "Москва"
    assert job.company == "Skyengteam"
    assert job.url == "https://skyengteam.potok.io/open/jobs/2747" and job.ats == "potok"
    assert all(s.url.startswith("https://skyengteam.potok.io/open/jobs/") for s in pages[0])


def test_empty_board_and_a_page_that_is_not_the_listing(search_pages, load_fixture):
    empty = _serve(**{"/open/jobs/": load_fixture("potok/list_empty.html")})
    assert search_pages(Potok(), empty, board="acme") == [[]]
    with pytest.raises(ValueError, match="no postings listing"):
        search_pages(Potok(), _serve(**{"/open/jobs/": "<html>app shell</html>"}), board="acme")


def test_fetch_details_reads_the_body_and_schedule(search_pages, fetch_details, load_fixture):
    list_html, detail = load_fixture("potok/list.html"), load_fixture("potok/detail_2747.html")
    stub = next(
        s
        for s in search_pages(Potok(), _serve(**{"/open/jobs/": list_html}), board="skyengteam")[0]
        if s.extra["id"] == "2747"
    )
    assert stub.description == "" and stub.remote is None
    full = fetch_details(Potok(), _serve(**{"/open/jobs/2747": detail}), stub)
    assert "PHP" in full.description
    assert "Откликнуться" not in full.description
    assert full.remote == "remote"  # schedule "Udalennaya rabota"
    assert full.title == stub.title


def test_fetch_details_keeps_the_stub_when_the_page_has_no_body(search_pages, fetch_details):
    stub = search_pages(
        Potok(),
        _serve(
            **{
                "/open/jobs/": '<div class="postings-wrapper"><div class="postings-group">'
                '<div class="posting"><a class="posting-title" href="/open/jobs/5">'
                "<h5>Dev</h5></a></div></div></div>"
            }
        ),
        board="acme",
    )[0][0]
    assert stub.title == "Dev" and stub.location == ""
    assert fetch_details(Potok(), _serve(**{"/open/jobs/5": "<html></html>"}), stub) == stub


def test_url_patterns():
    assert detect("https://skyengteam.potok.io/open/jobs/2747") == ("potok", "skyengteam")
    assert detect("potok:skyengteam") == ("potok", "skyengteam")
    assert detect("https://app.potok.io/login") is None
