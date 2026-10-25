from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.staffy import LIST, Staffy, parse_position, work_mode


def test_search_lists_then_reads_each_position(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages_by_path = {
        "/vacantes": load_fixture("staffy/listing.html"),
        "/positions/backend-engineer": load_fixture("staffy/position_backend.html"),
        "/positions/qa-analyst": load_fixture("staffy/position_qa.html"),
    }
    calls: list[str] = []
    pages = search_pages(
        Staffy(),
        lambda req: (
            httpx.Response(200, text=pages_by_path.get(req.url.path, ""))
            if req.url.path in pages_by_path
            else httpx.Response(404)
        ),
        calls=calls,
    )
    assert LIST in calls and len(pages) == 1
    backend, qa = pages[0]
    assert backend.title == "Backend Engineer" and backend.company == "Staffy"
    assert backend.url == "https://jobs.wearestaffy.com/positions/backend-engineer"
    assert backend.location == "Argentina" and backend.remote == "remote"
    assert backend.description.startswith("Responsibilities\n")
    assert "Build things." in backend.description and "great" in backend.description
    assert "New opportunity" not in backend.description  # the eyebrow above the metadata
    assert backend.extra["id"] == "backend-engineer" and backend.ats == "staffy"
    assert qa.location == "Buenos Aires" and qa.remote == "hybrid"


def test_a_missing_or_unreadable_position_is_left_out(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/vacantes":
            return httpx.Response(200, text=load_fixture("staffy/listing.html"))
        if req.url.path.endswith("qa-analyst"):
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>markup changed</body></html>")

    assert search_pages(Staffy(), handler) == [[]]  # one chunk, nothing readable in it


def test_helpers_and_task() -> None:
    assert parse_position("<html></html>", "https://jobs.wearestaffy.com/positions/x") is None
    assert [work_mode(x) for x in ("Remoto", "Híbrido (Puerto Madero)", "Presencial", "")] == [
        "remote",
        "hybrid",
        None,
        None,
    ]
    assert Staffy().tasks(SearchConfig())[0].board == LIST
