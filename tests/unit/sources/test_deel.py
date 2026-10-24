import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.deel import Deel, bracket_slice, decode_flight, text_rows
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _serve(html: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text=html)

    return handler


def _page(flight: str) -> str:
    return (
        f"<html><body><script>self.__next_f.push([1,{json.dumps(flight)}])</script></body></html>"
    )


def test_search_klarna_board(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Deel(), _serve(load_fixture("deel/klarna.html")), board="klarna")
    assert len(pages) == 1 and pages[0]
    job = pages[0][0]
    assert job.title.startswith("Customer Trust and Experience Consultant")
    assert job.company == "Klarna" and job.location == "Sweden"
    assert job.url == (
        "https://jobs.deel.com/klarna/job-details/5d3636f8-0712-4fe2-a1f4-84358440d272/overview"
    )
    assert len(job.description) > 200  # resolved from the "$23" text row, not left empty
    assert job.posted_at is not None and job.posted_at.year == 2025
    assert job.extra["board"] == "klarna" and job.ats == "deel"
    assert all(s.description for s in pages[0])


def test_empty_board(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Deel(), _serve(load_fixture("deel/empty.html")), board="klarna")
    assert pages == [[]]


def test_flight_primitives() -> None:
    # byte-length rows (a row may hold commas and multi-byte text); brackets inside strings
    flight = '1:["$","x"]\n2:T6,héllo!3:T3,a,b'
    assert text_rows(flight) == {"2": "héllo", "3": "a,b"}
    assert bracket_slice('{"a":[1,"]",[2]],"b":1}', '"a":', "[", "]") == '[1,"]",[2]]'
    assert bracket_slice("nothing", '"a":', "[", "]") is None
    assert decode_flight(_page("helloé")) == "helloé"
    with pytest.raises(ValueError, match=r"no Next\.js"):
        decode_flight("<html></html>")


def test_unresolved_descriptions_and_missing_postings(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    broken = '{"jobPostings":[{"id":"a","title":"T","richtextDescription":"$99","job":{}}]}'
    with pytest.raises(ValueError, match="none resolved"):
        search_pages(Deel(), _serve(_page(broken)), board="acme")
    with pytest.raises(ValueError, match="no postings"):
        search_pages(Deel(), _serve(_page("{}")), board="acme")
    inline = '{"jobPostings":[{"id":"a","title":"Dev","richtextDescription":"<p>Hi</p>"}]}'
    pages = search_pages(Deel(), _serve(_page(inline)), board="acme-inc")
    assert pages[0][0].description == "Hi" and pages[0][0].company == "Acme Inc"


def test_url_patterns() -> None:
    assert detect("https://jobs.deel.com/klarna") == ("deel", "klarna")
    assert detect("https://jobs.deel.com/klarna/job-details/abc/overview") == ("deel", "klarna")
    assert detect("deel:klarna") == ("deel", "klarna")
