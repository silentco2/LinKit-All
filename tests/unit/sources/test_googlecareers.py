from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.googlecareers import GoogleCareers, payload

URL = "https://www.google.com/about/careers/applications/jobs/results"


def test_payload_reads_records_and_total(load_fixture: Callable[[str], Any]) -> None:
    records, total = payload(load_fixture("googlecareers/google_full.html"))
    assert len(records) == 2 and total == 2
    assert payload(load_fixture("googlecareers/google_empty.html")) == ([], 3640)


def test_search_maps_the_inline_payload(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        GoogleCareers(),
        lambda req: httpx.Response(200, text=load_fixture("googlecareers/google_full.html")),
        board="www.google.com",
        calls=calls,
    )
    assert [c for c in calls if "robots" not in c] == [f"{URL}?page=1"]  # total 2 reached
    first, second = pages[0]
    assert first.title == "Staff Developer Experience Engineer, DeepMind"
    assert first.company == "Google" and first.extra["brand"] == "DeepMind"
    assert first.url == f"{URL}/132507027548054214"
    assert first.location == "Bengaluru, Karnataka, India"
    assert first.posted_at is not None and first.posted_at.isoformat() == "2026-01-15T00:00:00"
    # about the job, then responsibilities, then qualifications
    d = first.description
    assert d.index("DeepMind Developer Experience") < d.index("Define and lead")
    assert d.index("Define and lead") < d.index("Minimum qualifications")
    assert "<" not in d and first.ats == "googlecareers"
    assert (
        second.location == "Mountain View, CA, USA" and second.extra["id"] == "139289021426606790"
    )


def test_pages_until_empty_with_query(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params.get("page") == "1":
            return httpx.Response(200, text=load_fixture("googlecareers/google_list.html"))
        return httpx.Response(200, text=load_fixture("googlecareers/google_empty.html"))

    pages = search_pages(
        GoogleCareers(), handler, board="www.google.com", query="python dev", calls=calls
    )
    jobs = [c for c in calls if "robots" not in c]
    assert jobs == [f"{URL}?page=1&q=python+dev", f"{URL}?page=2&q=python+dev"]
    assert len(pages) == 1  # the empty second page ends the walk


def test_missing_payload_is_an_error(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    try:
        search_pages(
            GoogleCareers(),
            lambda req: httpx.Response(200, text="<html><body>no data</body></html>"),
            board="www.google.com",
        )
    except ValueError as e:
        assert "ds:1" in str(e)
    else:
        raise AssertionError("a changed page must not read as an empty catalogue")


def test_tasks_follow_queries() -> None:
    assert [t.query for t in GoogleCareers().tasks(SearchConfig())] == [""]
    cfg = SearchConfig(search={"queries": ["python"]})  # type: ignore[arg-type]
    tasks = GoogleCareers().tasks(cfg)
    assert tasks and all(t.query and t.key.startswith("googlecareers:") for t in tasks)
