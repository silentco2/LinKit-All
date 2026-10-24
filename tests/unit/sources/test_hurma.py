from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.hurma import Hurma, description
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _serve(
    load_fixture: Callable[[str], Any], seen: list[httpx.Request] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if req.url.path.endswith("/public-vacancies/406"):
            return httpx.Response(200, json=load_fixture("hurma/detail.json"))
        if req.url.params.get("page") == "1":
            return httpx.Response(200, json=load_fixture("hurma/list1.json"))
        if req.url.params.get("page") == "2":
            return httpx.Response(200, json=load_fixture("hurma/list2.json"))
        return httpx.Response(404)

    return handler


def test_search_pages_to_the_last_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []
    pages = search_pages(Hurma(), _serve(load_fixture, seen), board="scrumlaunch")
    assert [len(p) for p in pages] == [
        1,
        1,
    ]  # the entry without a /public-vacancies/<id> url is out
    first, second = pages[0][0], pages[1][0]
    assert first.title == "Senior UI/UX Designer"  # the "#406 " tag is gone
    assert first.url == "https://scrumlaunch.hurma.work/public-vacancies/406"
    assert first.location == "remote" and first.remote == "remote" and first.ats == "hurma"
    assert first.company == "Scrumlaunch"
    assert first.extra == {
        "board": "scrumlaunch",
        "id": "406",
        "employment": "Full-time, Remote work",
    }
    assert second.title == "QA Engineer" and second.remote is None
    assert all(r.headers["X-Requested-With"] == "XMLHttpRequest" for r in seen)
    assert all(r.headers["User-Agent"] != "" for r in seen)


def test_resume_from_a_later_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Hurma(), _serve(load_fixture), board="scrumlaunch", start_page=1, calls=calls
    )
    assert [p[0].title for p in pages] == ["QA Engineer"]
    assert len(calls) == 1


def test_fetch_details_stitches_the_sections(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="hurma",
        url="https://scrumlaunch.hurma.work/public-vacancies/406",
        title="Senior UI/UX Designer",
        company="Scrumlaunch",
    )
    done = fetch_details(Hurma(), _serve(load_fixture), stub)
    text = done.description
    assert text.startswith("We are looking for a designer.")
    assert "Requirements" in text and "- 5+ years" in text and "Working conditions" in text
    assert "x()" not in text  # scripts are not text
    assert done.remote == "remote"


def test_description_skips_empty_sections() -> None:
    text = description({"description": "A", "demand": "  ", "addition": "B"})
    assert "A" in text and "B" in text and "Requirements" not in text


def test_url_patterns() -> None:
    assert detect("https://scrumlaunch.hurma.work/public-vacancies/406") == ("hurma", "scrumlaunch")
    assert detect("hurma:acme") == ("hurma", "acme")
