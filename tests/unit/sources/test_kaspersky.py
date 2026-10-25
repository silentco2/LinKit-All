import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.kaspersky import HOST, Kaspersky, listing
from linkit_all.sources.http import Http

EMPTY = (
    '<html><body><script>self.__next_f.push([1,"6:[{\\"vacancies\\":[],\\"totalCount\\":85}]"])'
    "</script></body></html>"
)


def test_listing_reads_the_flight(load_fixture: Callable[[str], Any]) -> None:
    items, total = listing(load_fixture("kaspersky/kaspersky_list.html"))
    assert total == 85 and [i["jobReqId"] for i in items] == [
        "25358",
        "25969",
        "668bbf4ab63848f9dd858476",
    ]
    try:
        listing("<html><body>nothing</body></html>")
    except ValueError as e:
        assert "listing array" in str(e)
    else:
        raise AssertionError("a flight without the array must be an error")


def test_search_maps_postings_and_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        page = req.url.params["page"]
        return httpx.Response(
            200, text=load_fixture("kaspersky/kaspersky_list.html") if page == "0" else EMPTY
        )

    pages = search_pages(Kaspersky(), handler, board=HOST, calls=calls)
    assert [c for c in calls if "robots" not in c] == [
        f"https://{HOST}/vacancies?page=0",
        f"https://{HOST}/vacancies?page=1",
    ]
    assert len(pages) == 1
    acc, go, great = pages[0]
    assert acc.title == "Senior Accountant" and acc.company == "Kaspersky"
    assert acc.url == f"https://{HOST}/vacancy/25358" and acc.location == "Taipei City"
    assert go.location == "Russia, Moscow" and go.extra["skills"] == ["Golang (Go)"]
    assert great.extra["id"] == "668bbf4ab63848f9dd858476" and great.extra["categories"] == [
        "Information Security"
    ]
    assert go.description == ""


def run_details(handler: Callable[[httpx.Request], httpx.Response], stub: JobStub) -> JobStub:
    async def go() -> JobStub:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            return await Kaspersky().fetch_details(Http(client, attempts=1), stub)

    return asyncio.run(go())


def test_details_read_the_body_and_skip_a_closed_requisition(
    load_fixture: Callable[[str], Any],
) -> None:
    stub = JobStub(
        source="kaspersky", url=f"https://{HOST}/vacancy/25969", title="x", company="Kaspersky"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/vacancy/25969":
            return httpx.Response(200, text=load_fixture("kaspersky/kaspersky_vacancy.html"))
        if req.url.path == "/vacancy/1":  # closed: sent back to the listing
            return httpx.Response(307, headers={"location": f"https://{HOST}/vacancies"})
        return httpx.Response(200, text="<html><body>list</body></html>")

    full = run_details(handler, stub)
    assert "OSMP (Open Single Management Platform)" in full.description
    assert "<" not in full.description
    gone = run_details(handler, stub.model_copy(update={"url": f"https://{HOST}/vacancy/1"}))
    assert gone.description == ""


def test_task() -> None:
    assert Kaspersky().tasks(SearchConfig())[0].board == HOST
