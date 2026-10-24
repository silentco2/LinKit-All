from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.zoho import Zoho, detail_of, js_unescape
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def handler_for(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/jobs/Careers":
            return httpx.Response(200, text=load_fixture("zoho/careers.html"))
        if path == "/jobs/Careers/100":
            return httpx.Response(200, text=load_fixture("zoho/detail_100.html"))
        if path == "/jobs/Careers/200":
            return httpx.Response(200, text=load_fixture("zoho/detail_200.html"))
        return httpx.Response(404)  # robots.txt, and posting 400 that has since been removed

    return handler


def test_lists_published_openings_and_reads_each_record(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Zoho(), handler_for(load_fixture), board="acme.zohorecruit.com")
    assert len(pages) == 1
    backend, designer = pages[0]  # 300 is unpublished, 400 has no detail page
    assert backend.title == "Backend Engineer" and backend.company == "Acme"
    assert backend.url == "https://acme.zohorecruit.com/jobs/Careers/100"
    assert backend.location == "Lisbon, Portugal" and backend.remote is None
    assert "Duties" in backend.description and "audit files." in backend.description
    assert "\\" not in backend.description and "&lt;" not in backend.description
    assert "•" in backend.description  # the doubly-escaped bullet
    assert backend.posted_at is not None and backend.posted_at.date().isoformat() == "2024-11-11"
    assert backend.extra == {"board": "acme.zohorecruit.com", "id": "100"}
    assert designer.title == "Remote Designer" and designer.description == "Design things"
    assert designer.remote == "remote" and designer.location == ""
    assert designer.posted_at is None  # this record has no Date_Opened


def test_missing_data_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    nothing = lambda req: httpx.Response(200, text="<html><body>x</body></html>")  # noqa: E731
    with pytest.raises(ValueError, match="no #jobs data"):
        search_pages(Zoho(), nothing, board="acme.zohorecruit.com")
    resumed = search_pages(
        Zoho(), handler_for(load_fixture), board="acme.zohorecruit.com", start_page=1
    )
    assert resumed == []


def test_unescape_and_detail_parsing() -> None:
    cases = {
        r"\x3Cp\x3EHello\x3C/p\x3E": "<p>Hello</p>",
        r"a\x22b\x22c": 'a"b"c',
        r"line\nbreak": "line\nbreak",
        r"path\/to": "path/to",
        "plain": "plain",
        r"<\\\/span>": "</span>",  # escaped twice
        r"\\u2022": "•",
        r"\\\x22q\\\x22": '"q"',
        r"margin\-top": "margin-top",
    }
    for raw, want in cases.items():
        assert js_unescape(raw) == want
    page = r"x \x22Job_Description\x22:\x22\x3Cp\x3EBody\x3C/p\x3E\x22,\x22Date_Opened\x22:\x222024\-13\-45\x22"
    assert detail_of(page) == ("<p>Body</p>", "2024-13-45")  # the date is judged later
    assert detail_of("no record here") is None


def test_url_patterns() -> None:
    assert detect("https://lithan.zohorecruit.com/jobs/Careers/774297000000901001") == (
        "zoho",
        "lithan.zohorecruit.com",
    )
    assert detect("https://talcom.zohorecruit.eu/jobs/Careers") == ("zoho", "talcom.zohorecruit.eu")
    assert detect("zoho:acme.zohorecruit.com") == ("zoho", "acme.zohorecruit.com")
