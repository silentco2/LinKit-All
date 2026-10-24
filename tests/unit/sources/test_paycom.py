from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import paycom
from linkit_all.sources.ats.paycom import Paycom
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

MANTLE = "portal-applicant-tracking.us-cent.paycomonline.net"


def make_handler(
    load_fixture: Callable[[str], Any], portal: str = "portal.html", name: bool = True
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "www.paycomonline.net":
            assert path.endswith("/portal/CK/jobs/1")
            return httpx.Response(200, text=load_fixture(f"paycom/{portal}"))
        assert req.url.host == MANTLE
        # the portal's own script sends the session token it was given, with a locale
        assert req.headers["Authorization"] == "JWT123" and req.headers["Locale"] == "en-US"
        if path == "/api/ats/company-name":
            if not name:
                return httpx.Response(404)
            return httpx.Response(200, json={"companyName": "City Electric Supply"})
        if path == "/api/ats/job-posting-previews/search":
            return httpx.Response(200, json=load_fixture("paycom/previews.json"))
        ident = path.rsplit("/", 1)[1]
        return httpx.Response(200, json=load_fixture(f"paycom/detail_{ident}.json"))

    return handler


def test_bootstrap_list_and_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Paycom(), make_handler(load_fixture), board="CK")
    driver, gear = pages[0]
    assert driver.title == "Van Driver" and driver.company == "City Electric Supply"
    assert driver.url == "https://www.paycomonline.net/v4/ats/web.php/portal/CK/jobs/546849"
    assert driver.location == "Centennial, CO" and driver.remote is None and driver.ats == "paycom"
    assert "Drive a van." in driver.description and "x()" not in driver.description
    assert driver.posted_at is not None and driver.posted_at.date().isoformat() == "2026-06-20"
    assert driver.extra == {"board": "CK", "id": "546849"}
    assert gear.remote == "remote" and "Quote gears." in gear.description  # escaped HTML decoded


def test_company_name_is_optional(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Paycom(), make_handler(load_fixture, name=False), board="CK")
    assert pages[0][0].company == "Ck"


def test_posts_the_search_body_and_pages(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paycom, "CHUNK", 1)
    bodies: list[str] = []
    inner = make_handler(load_fixture)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            bodies.append(req.content.decode())
        return inner(req)

    assert len(search_pages(Paycom(), handler, board="CK")) == 2
    assert '"skip":0' in bodies[0].replace(" ", "") and '"take":50' in bodies[0].replace(" ", "")
    assert len(bodies) == 1  # the stated count (2) was reached on the first page
    resumed = search_pages(Paycom(), handler, board="CK", start_page=1)
    assert [j.title for p in resumed for j in p] == ["Gear Specialist"]


def test_missing_board_and_missing_token(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        search_pages(Paycom(), make_handler(load_fixture, "no_board.html"), board="CK")
    with pytest.raises(ValueError, match="no session token"):
        search_pages(
            Paycom(),
            lambda r: httpx.Response(404 if "robots" in r.url.path else 200, text="<html/>"),
            board="CK",
        )


def test_url_patterns() -> None:
    url = "https://www.paycomonline.net/v4/ats/web.php/portal/0A3F9C/jobs/546849"
    assert detect(url) == ("paycom", "0A3F9C")
    assert detect("https://www.paycomonline.net/v4/ats/index.php/jobs?clientkey=0A3F9C") == (
        "paycom",
        "0A3F9C",
    )
