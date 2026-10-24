import httpx
import pytest

from linkit_all.sources.ats.bamboohr import BambooHR
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.careers import Unsupported


def test_search_maps_the_list(search_pages, load_fixture):
    data = load_fixture("bamboohr/list.json")
    calls: list[str] = []
    pages = search_pages(
        BambooHR(), lambda req: httpx.Response(200, json=data), board="acme", calls=calls
    )
    a, b = pages[0]
    assert (a.title, a.company, a.location) == ("Senior Designer", "Acme", "Yerevan")
    assert a.url == "https://acme.bamboohr.com/careers/52"
    assert a.remote == "onsite"
    assert a.extra["id"] == "52" and a.ats == "bamboohr"
    assert b.remote == "remote"  # isRemote true, no locationType
    assert calls == ["https://acme.bamboohr.com/careers/list"]


def test_a_board_that_redirects_off_careers_is_not_served(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/careers/list":
            return httpx.Response(302, headers={"location": "https://acme.bamboohr.com/login.php"})
        return httpx.Response(200, text="<html>login</html>")

    # the mock client does not follow redirects by itself; the real one does (make_client)
    async def go() -> None:
        from linkit_all.sources.base import Task
        from linkit_all.sources.http import Http

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            task = Task("bamboohr", "bamboohr:acme", board="acme")
            async for _ in BambooHR().search(Http(client, attempts=1), task, 0):
                pass

    import asyncio

    with pytest.raises(Unsupported, match=r"login.php"):
        asyncio.run(go())


def test_fetch_details(search_pages, fetch_details, load_fixture):
    data = load_fixture("bamboohr/list.json")
    stub = search_pages(BambooHR(), lambda req: httpx.Response(200, json=data), board="acme")[0][0]
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("bamboohr/detail_52.json"))

    out = fetch_details(BambooHR(), handler, stub)
    assert seen == ["/careers/52/detail"]
    assert "Do the work." in out.description and "x()" not in out.description
    assert out.location == "Yerevan, Armenia"
    assert out.posted_at is not None and out.posted_at.year == 2025


def test_an_empty_detail_is_not_an_answer(search_pages, fetch_details, load_fixture):
    data = load_fixture("bamboohr/list.json")
    stub = search_pages(BambooHR(), lambda req: httpx.Response(200, json=data), board="acme")[0][0]
    out = fetch_details(BambooHR(), lambda req: httpx.Response(200, json={"result": None}), stub)
    assert out == stub


def test_url_patterns():
    assert detect("https://acme.bamboohr.com/careers/52", [BambooHR()]) == ("bamboohr", "acme")
