from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.loxo import Loxo, job_id
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

REMOTE_JOB = "NDI0NzQtN3RzZTNpa2M2NDJ5emowdg=="
OTHER_JOB = "NDI0NzQtMGdnbGYwaWhjZGR1N3UwZw=="


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))
    yield


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/fitnext":
            return httpx.Response(200, text=load_fixture("loxo/listing.html"))
        if path == f"/job/{REMOTE_JOB}":
            return httpx.Response(200, text=load_fixture("loxo/detail.html"))
        if path == f"/job/{OTHER_JOB}":
            return httpx.Response(200, text=load_fixture("loxo/detail_no_og.html"))
        return httpx.Response(404)  # the third posting is gone

    return handler


@pytest.mark.parametrize("host", ["fitnext.app.loxo.co", "pod4.app.loxo.co", "app.loxo.co"])
def test_listing_then_details(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    host: str,
) -> None:
    pages = search_pages(Loxo(), make_handler(load_fixture), board=f"{host}/fitnext")
    assert len(pages) == 1 and len(pages[0]) == 2
    a, b = pages[0]
    assert a.title == "Frontend Engineer (React + TypeScript)"
    assert a.url == f"https://{host}/job/{REMOTE_JOB}"
    assert a.extra == {"board": f"{host}/fitnext", "id": "42474-7tse3ikc642yzj0v"}
    assert a.company == "Fitnext" and a.location == "Remote (LATAM)" and a.remote == "remote"
    assert "Build the UI. & ship." in a.description and "alert" not in a.description
    assert b.title == "Backend Engineer"  # from the document title, agency suffix removed
    assert b.location == "" and b.description == "Server side."


def test_resume_skips_earlier_chunks(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        Loxo(), make_handler(load_fixture), board="app.loxo.co/fitnext", start_page=1
    )
    assert pages == []


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="loxo",
        url=f"https://app.loxo.co/job/{OTHER_JOB}?t=1",
        title="t",
        company="c",
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("loxo/detail_no_og.html"))

    assert fetch_details(Loxo(), handler, stub).description == "Server side."


def test_job_id() -> None:
    assert job_id(f"https://fitnext.app.loxo.co/job/{REMOTE_JOB}") == "42474-7tse3ikc642yzj0v"
    assert job_id(f"https://app.loxo.co/job/{OTHER_JOB}?t=1783700180") == "42474-0gglf0ihcddu7u0g"
    assert job_id("https://app.loxo.co/job/YWJjLTE=") == "abc-1"
    assert job_id("https://app.loxo.co/job/abcd") == "abcd"  # does not decode to <id>-<slug>
    assert job_id("https://app.loxo.co/fitnext") == ""


def test_url_patterns() -> None:
    assert detect("https://fitnext.app.loxo.co/fitnext") == ("loxo", "fitnext.app.loxo.co/fitnext")
    assert detect("https://pod4.app.loxo.co/acme/jobs") == ("loxo", "pod4.app.loxo.co/acme")
    assert detect("https://app.loxo.co/acme") == ("loxo", "app.loxo.co/acme")
    assert detect("loxo:app.loxo.co/acme") == ("loxo", "app.loxo.co/acme")
