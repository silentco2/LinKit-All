from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.vention import HOST, Vention, work_mode


def test_search_maps_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Vention(),
        lambda req: httpx.Response(200, json=load_fixture("vention/page0.json")),
        board=HOST,
        calls=calls,
    )
    assert calls[0].startswith(f"https://{HOST}/api/v2/pages/?type=join_vacancy.VacancyPage")
    assert calls[0].endswith("limit=20&offset=0")
    assert len(pages) == 1 and len(pages[0]) == 1
    job = pages[0][0]
    assert job.title == "Python Intern" and job.company == "Vention"
    assert job.url == "https://join.ventionteams.com/job-openings/internship-python-krakow"
    assert job.location == "Krakow, Poland" and job.remote == "remote"
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-06-14T18:39:35"
    assert job.extra["id"] == "1652"
    for part in ("Do", "work", "Python", "perks", "us"):  # all four blocks, in order
        assert part in job.description
    assert "x" not in job.description.split()  # the script body is dropped


def test_pages_until_total_count_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    offsets: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        offset = int(req.url.params["offset"])
        offsets.append(str(offset))
        n = 20 if offset == 0 else 5
        items = [
            {"id": offset + i + 1, "title": f"J{offset + i}", "meta": {"slug": "s"}}
            for i in range(n)
        ]
        return httpx.Response(200, json={"meta": {"total_count": 25}, "items": items})

    pages = search_pages(Vention(), handler, board=HOST)
    assert offsets == ["0", "20"] and [len(p) for p in pages] == [20, 5]
    assert pages[0][0].url == f"https://{HOST}/job-openings/s"  # no html_url: built from the slug
    offsets.clear()
    search_pages(Vention(), handler, board=HOST, start_page=1)
    assert offsets == ["20"]


def test_work_mode_and_task() -> None:
    assert [
        work_mode(f) for f in ("remote", "city_hybrid", "city_onsite", "office", "?", None)
    ] == [
        "remote",
        "hybrid",
        "onsite",
        "onsite",
        None,
        None,
    ]
    tasks = Vention().tasks(SearchConfig())
    assert [(t.source, t.board) for t in tasks] == [("vention", HOST)]
    assert Vention().kind == "company" and not Vention().is_enabled(SearchConfig())
