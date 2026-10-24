from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.erecruiter import ERecruiter, parse_offer, parse_rows
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

CFG = "4D3DD27FCA3D40C79E01BEE9745902B7"


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/GetHtml.ashx":
            n = req.url.params["pn"]
            return httpx.Response(
                200, text=load_fixture(f"erecruiter/list_{n}.txt") if n in "12" else '({"htm":""})'
            )
        if req.url.params["oid"] == "4882523":  # a closed offer: page without a title or body
            return httpx.Response(200, text="<html><body></body></html>")
        return httpx.Response(200, text=load_fixture("erecruiter/detail.html"))

    return handler


def test_parse_rows(load_fixture: Callable[[str], Any]) -> None:
    rows, total, size = parse_rows(load_fixture("erecruiter/list_1.txt"))
    assert (total, size) == (4, 3) and len(rows) == 3
    assert rows[1] == {
        "oid": "4882522", "ejoid": "570550", "ejorid": "308328", "comid": "20002054",
        "title": "Specjalista ds. Wsparcia", "city": "Łódź",
    }  # fmt: skip
    assert parse_rows("  ") == ([], 0, 0)


def test_parse_offer(load_fixture: Callable[[str], Any]) -> None:
    title, place, text = parse_offer(load_fixture("erecruiter/detail.html"))
    assert (title, place) == ("Specjalista ds. Wsparcia", "Łódź")
    assert "Prowadzenie połączeń" in text and "40 lat" in text
    assert "evil" not in text and "zgodę" not in text and "Miejsce pracy" not in text


def test_pages_stop_at_the_reported_total(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        ERecruiter(), make_handler(load_fixture), board=f"{CFG}/acme-corp", calls=calls
    )
    assert [len(p) for p in pages] == [2, 1]  # the closed offer (4882523) is dropped
    assert sum("GetHtml" in c for c in calls) == 2  # tr=4, ps=3: page 2 is the last
    a = pages[0][0]
    assert a.title == "Specjalista ds. Wsparcia" and a.company == "Acme Corp"
    assert a.location == "Łódź" and a.ats == "erecruiter"
    assert a.url == (
        f"https://skk.erecruiter.pl/Offer.aspx?oid=4891462&cfg={CFG}"
        "&ejoId=574507&ejorId=309263&comId=20002054"
    )
    assert a.extra == {"board": f"{CFG}/acme-corp", "id": "4891462"}


def test_resume_without_company(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(ERecruiter(), make_handler(load_fixture), board=CFG, start_page=1)
    assert [len(p) for p in pages] == [1] and pages[0][0].company == "Unknown"


def test_bad_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="32-hex"):
        search_pages(ERecruiter(), lambda r: httpx.Response(200), board="acme")


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="erecruiter",
        url=f"https://skk.erecruiter.pl/Offer.aspx?oid=4891462&cfg={CFG}&ejoId=1&ejorId=2&comId=3",
        title="t",
        company="c",
    )
    assert (
        "Prowadzenie" in fetch_details(ERecruiter(), make_handler(load_fixture), stub).description
    )


def test_url_patterns() -> None:
    page = f"<script src='https://skk.erecruiter.pl/Code.ashx?cfg={CFG}'></script>"
    assert detect(page) == ("erecruiter", CFG)
    assert detect(f"erecruiter:{CFG}") == ("erecruiter", CFG)
