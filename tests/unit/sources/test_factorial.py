from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.factorial import Factorial, location_of
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

HOST = "acme.factorial.it"


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/":
            return httpx.Response(200, text=load_fixture("factorial/listing.html"))
        n = "100" if path.endswith("-100") else "200"
        return httpx.Response(200, text=load_fixture(f"factorial/job_{n}.html"))

    return handler


def test_listing_then_jobs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Factorial(), make_handler(load_fixture), board=HOST)
    assert len(pages) == 1 and len(pages[0]) == 2  # duplicate link merged, id-less link dropped
    a, b = pages[0]
    assert a.title == "Backend Engineer" and a.company == "Acme"
    assert a.url == f"https://{HOST}/job_posting/backend-engineer-100"
    assert a.location == "Milano, Italia" and a.remote == "hybrid"
    assert a.description == "Build things" and a.posted_at is None
    assert a.extra == {"board": HOST, "id": "100"}
    assert b.location == "Madrid, España" and b.remote == "remote"


def test_resume_and_details(
    search_pages: Callable[..., list[list[JobStub]]],
    fetch_details: Callable[..., JobStub],
    load_fixture: Callable[[str], Any],
) -> None:
    handler = make_handler(load_fixture)
    assert search_pages(Factorial(), handler, board=HOST, start_page=1) == []
    stub = JobStub(
        source="factorial", url=f"https://{HOST}/job_posting/x-200", title="t", company="c"
    )
    assert fetch_details(Factorial(), handler, stub).description == "Analyze data"


@pytest.mark.parametrize(
    ("rows", "want"),
    [
        (
            ["Clt", "R$1.937,6 Mensal", "RIO DAS OSTRAS, RJ, Brasil", "QUALIDADE"],
            ("RIO DAS OSTRAS, RJ, Brasil", None),
        ),
        (["Full time", "TRIVENETO", "S - Partnerships (PAR)"], ("", None)),
        (["Remoto (Madrid, España)"], ("Madrid, España", "remote")),
        (["Presencial (Lisboa, Portugal)"], ("Lisboa, Portugal", "onsite")),
    ],
)
def test_location_of(rows: list[str], want: tuple[str, str | None]) -> None:
    assert location_of(rows) == want


def test_url_patterns() -> None:
    assert detect(f"https://{HOST}/job_posting/x-1") == ("factorial", HOST)
    assert detect("https://highbras.factorialhr.com.br/") == (
        "factorial",
        "highbras.factorialhr.com.br",
    )
    assert detect("https://muffin.factorialhr.com/") == ("factorial", "muffin.factorialhr.com")
    assert detect("https://www.factorialhr.com/blog") is None
    assert detect(f"factorial:{HOST}") == ("factorial", HOST)
