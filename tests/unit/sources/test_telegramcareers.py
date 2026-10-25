from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.telegramcareers import PAGE, TelegramCareers, parse_page


def ok(text: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: httpx.Response(404 if req.url.path == "/robots.txt" else 200, text=text)


def test_search_splits_roles_on_headings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    html = load_fixture("telegramcareers/jobs.html")
    pages = search_pages(TelegramCareers(), ok(html))
    first, second = pages[0]
    assert (first.title, first.company) == ("Content Moderator", "Telegram")
    assert first.url == f"{PAGE}?role=content-moderator" and first.location == ""
    assert (
        "Responsibilities:" in first.description
        and "sort" in first.description
        and "care" in first.description
    )
    assert second.title == "C/C++ Software Engineer" and second.url.endswith(
        "?role=c-c-software-engineer"
    )
    assert "storage engines" in second.description and "x" not in second.description.split()
    assert first.ats == "telegramcareers" and first.extra["id"] == "content-moderator"


def test_page_without_content_and_task() -> None:
    assert parse_page("<html><body>nothing</body></html>") == []
    assert [t.board for t in TelegramCareers().tasks(SearchConfig())] == [PAGE]
