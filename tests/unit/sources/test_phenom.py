import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import phenom
from linkit_all.sources.ats.phenom import Phenom, job_url, posted
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

HOST = "careers.example.de"


def make_handler(
    load_fixture: Callable[[str], Any], bodies: list[dict[str, Any]] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST" and req.url.host == HOST and req.url.path == "/widgets"
        body = json.loads(req.content)
        if bodies is not None:
            bodies.append(body)
        if body["ddoKey"] == "refineSearch":
            page = {0: "page1", 2: "page2"}.get(body["from"])
            if page is None:
                return httpx.Response(200, json={"refineSearch": {"data": {"jobs": []}}})
            return httpx.Response(200, json=load_fixture(f"phenom/{page}.json"))
        assert body["ddoKey"] == "jobDetail" and body["pageName"] == "job-details"
        if body["jobSeqNo"] == "R2":  # no body: the posting is dropped
            return httpx.Response(200, json=load_fixture("phenom/detail_empty.json"))
        return httpx.Response(200, json=load_fixture(f"phenom/detail_{body['jobSeqNo']}.json"))

    return handler


def test_list_pages_then_details(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phenom, "PAGE", 2)
    bodies: list[dict[str, Any]] = []
    pages = search_pages(Phenom(), make_handler(load_fixture, bodies), board=HOST)
    assert [len(p) for p in pages] == [1, 1]  # R2 has no description
    r1, r3 = pages[0][0], pages[1][0]
    assert r1.title == "Engineer R1" and r1.location == "Bonn, NRW" and r1.company == "Example"
    assert r1.url == f"https://{HOST}/global/en/job/R1" and r1.ats == "phenom"
    assert "Build things R1." in r1.description and "x()" not in r1.description
    assert r1.posted_at is not None and r1.posted_at.isoformat() == "2026-05-17T22:00:00"
    assert r3.url == f"https://{HOST}/job/R3" and r3.remote == "remote"  # no locale: plain path
    assert r1.extra == {"board": HOST, "id": "R1"}
    lists = [b for b in bodies if b["ddoKey"] == "refineSearch"]
    assert [b["from"] for b in lists] == [0, 2] and lists[0]["size"] == 2


def test_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(phenom, "PAGE", 2)
    bodies: list[dict[str, Any]] = []
    pages = search_pages(Phenom(), make_handler(load_fixture, bodies), board=HOST, start_page=1)
    assert [j.extra["id"] for p in pages for j in p] == ["R3"]
    assert bodies[0]["from"] == 2


def test_helpers() -> None:
    assert job_url("h.com", "de_DE", "9") == "https://h.com/de/de/job/9"
    assert job_url("h.com", None, "9") == "https://h.com/job/9"
    when = posted("2026-05-17T22:00:00.000+0200")
    assert when is not None and when.hour == 20
    assert posted("yesterday") is None and posted(None) is None


def test_bad_board_and_shorthand(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="careers host"):
        search_pages(Phenom(), lambda r: httpx.Response(200), board="acme")
    assert detect(f"phenom:{HOST}") == ("phenom", HOST)
