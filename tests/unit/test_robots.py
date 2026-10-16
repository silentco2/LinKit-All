import asyncio
from pathlib import Path

import httpx

from linkit_all.sources.http import Http, Robots

FORASNA = (Path(__file__).parent.parent / "fixtures" / "forasna" / "robots.txt").read_text("utf-8")
WUZZUF = "User-agent: *\nDisallow: /*?q=\nDisallow: /api/\nCrawl-delay: 10\n"
H = "https://x.test"


def ok(text: str, path: str) -> bool:
    return Robots(text).can_fetch(H + path)


def test_wildcards_and_end_anchor() -> None:
    txt = "User-agent: *\nDisallow: /*.pdf$\nDisallow: /a*b/c\n"
    assert not ok(txt, "/files/cv.pdf")
    assert ok(txt, "/files/cv.pdf?x=1")  # $ anchors at the end of path+query
    assert ok(txt, "/files/cv.pdfx")
    assert not ok(txt, "/aXXb/c/d")
    assert ok(txt, "/a/c")


def test_longest_match_wins_and_allow_wins_ties() -> None:
    txt = "User-agent: *\nDisallow: /private/\nAllow: /private/public/\nDisallow: /same\nAllow: /same\n"
    assert not ok(txt, "/private/x")
    assert ok(txt, "/private/public/x")
    assert ok(txt, "/same")  # equal length: Allow wins
    assert Robots("User-agent: *\nDisallow:\n").can_fetch(H + "/anything")  # empty = allow


def test_two_star_groups_merge_forasna_style() -> None:
    r = Robots(FORASNA)
    assert r.crawl_delay == 10  # only in the third group
    assert r.can_fetch("https://forasna.com/job/p/accountant-123")
    assert not r.can_fetch("https://forasna.com/cgi-bin/x")
    assert not r.can_fetch("https://forasna.com/jobs?query=a")
    assert not r.can_fetch("https://forasna.com/job/p/evaluation-manager-1")  # /*uat*
    assert not r.can_fetch("https://forasna.com/x/staging/y")


def test_specific_agent_group_beats_star() -> None:
    txt = "User-agent: *\nAllow: /\n\nUser-agent: linkitall\nUser-agent: Other\nDisallow: /jobs\n"
    assert not ok(txt, "/jobs/1")
    assert ok(txt, "/about")
    assert Robots("User-agent: Other\nDisallow: /\n").can_fetch(H + "/jobs")  # not our group


def test_crawl_delay_max_of_selected_groups() -> None:
    txt = "User-agent: *\nCrawl-delay: 2\n\nUser-agent: *\nCrawl-delay: 7\nUser-agent: x\n"
    assert Robots(txt).crawl_delay == 7
    assert Robots("User-agent: *\nCrawl-delay: nope\n").crawl_delay is None


def test_wuzzuf_search_disallowed_job_pages_allowed() -> None:
    assert not ok(WUZZUF, "/search/jobs?q=python")
    assert not ok(WUZZUF, "/jobs/p/abc?q=x")
    assert ok(WUZZUF, "/jobs/p/abc-engineer-cairo")
    assert Robots(WUZZUF).crawl_delay == 10


def test_percent_encoding_and_robots_txt_itself() -> None:
    txt = "User-agent: *\nDisallow: /\n"
    assert ok(txt, "/robots.txt")
    arabic = "User-agent: *\nDisallow: /وظائف\n"
    assert not ok(arabic, "/%D9%88%D8%B8%D8%A7%D8%A6%D9%81/1")
    assert not ok("User-agent: *\nDisallow: /%e0%a4%ab\n", "/%E0%A4%AB")  # case of hex ignored
    assert not ok("User-agent: *\nDisallow: /a-b\n", "/a%2Db")  # unreserved decoded


def _http(status: int, text: str = "") -> Http:
    return Http(
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, text=text))
        )
    )


def test_error_statuses() -> None:
    url = "https://x.test/jobs"
    assert asyncio.run(_http(404).allowed(url)) is True
    assert asyncio.run(_http(503).allowed(url)) is False
    assert asyncio.run(_http(429).allowed(url)) is False
    assert asyncio.run(_http(200, "User-agent: *\nDisallow: /*jobs$\n").allowed(url)) is False
