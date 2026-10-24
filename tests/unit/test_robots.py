import asyncio
from pathlib import Path

import httpx

from linkit_all.sources.http import Http, crawl_delay

FORASNA = (Path(__file__).parent.parent / "fixtures" / "forasna" / "robots.txt").read_text("utf-8")


def test_crawl_delay_forasna_third_group() -> None:
    assert crawl_delay(FORASNA) == 10  # only in the third `*` group


def test_specific_agent_group_beats_star() -> None:
    txt = "User-agent: *\nCrawl-delay: 2\n\nUser-agent: linkitall\nUser-agent: Other\nCrawl-delay: 5\n"
    assert crawl_delay(txt) == 5
    assert crawl_delay("User-agent: Other\nCrawl-delay: 9\n") is None  # not our group


def test_crawl_delay_max_of_selected_groups() -> None:
    txt = "User-agent: *\nCrawl-delay: 2\n\nUser-agent: *\nCrawl-delay: 7\nUser-agent: x\n"
    assert crawl_delay(txt) == 7
    assert crawl_delay("User-agent: *\nCrawl-delay: nope\n") is None


def _http(status: int, text: str = "") -> tuple[Http, list[str]]:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(status, text=text)

    return Http(httpx.AsyncClient(transport=httpx.MockTransport(handler))), paths


def test_disallowed_path_is_still_allowed_and_crawl_delay_slows_the_host() -> None:
    http, paths = _http(200, "User-agent: *\nDisallow: /\nCrawl-delay: 10\n")
    assert asyncio.run(http.allowed("https://x.test/jobs")) is True
    assert asyncio.run(http.allowed("https://x.test/other")) is True
    assert paths == ["/robots.txt"]  # read once per host
    assert http._rates["x.test"] == 0.1


def test_failing_robots_changes_nothing() -> None:
    for status in (404, 429, 503):
        http, _ = _http(status, "Crawl-delay: 10")
        assert asyncio.run(http.allowed("https://x.test/jobs")) is True
        assert "x.test" not in http._rates

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    http = Http(httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    assert asyncio.run(http.allowed("https://x.test/jobs")) is True
