from collections.abc import Callable
from typing import Any

import httpx
from boards_util import router, run_search

from linkit_all.sources.boards.techtree import TechTree

JOB = "8773660e-c2c3-4b49-9d03-6f9f76859bc8"


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "jobs.techtree.dev/sitemap.xml": load_fixture("techtree/sitemap.xml"),
        f"/job/{JOB}": load_fixture("techtree/job_telepatia.html"),
        "/job/0515f6f5": (404, "gone"),
    }


def test_sitemap_then_posting_pages(load_fixture: Callable[[str], Any]) -> None:
    calls: list[httpx.Request] = []
    pages = run_search(TechTree(), router(_routes(load_fixture), calls))
    assert (
        len(pages) == 1 and len(pages[0]) == 1
    )  # the 404 posting is skipped, other pages are no jobs
    job = pages[0][0]
    assert job.title == "Mid/Senior AI Engineer, New Products (0→1)"
    assert job.company == "Telepatia" and job.location == "Latin America (remote)"
    assert job.url == f"https://jobs.techtree.dev/job/{JOB}"
    assert job.extra["id"] == JOB and job.ats == "techtree" and job.remote == "remote"
    assert "Telepatia AI is a healthtech company" in job.description  # from the .prose element
    assert job.posted_at is not None and (job.posted_at.month, job.posted_at.day) == (9, 11)
    paths = [r.url.path for r in calls]
    assert "/" not in paths[1:] and "/talent-scout" not in paths  # only /job/ pages are fetched
    assert paths.index(f"/job/{JOB}") < paths.index(
        "/job/0515f6f5-8f30-4cb6-abd2-16bf87137a4d"
    )  # newest first


def test_resume_and_limit(load_fixture: Callable[[str], Any]) -> None:
    assert run_search(TechTree(), router(_routes(load_fixture)), start_page=1) == []
    (limited,) = run_search(TechTree(), router(_routes(load_fixture)), limit=1)
    assert [s.extra["id"] for s in limited] == [JOB]


def test_page_without_a_body_is_not_stored(load_fixture: Callable[[str], Any]) -> None:
    routes = _routes(load_fixture)
    routes[f"/job/{JOB}"] = load_fixture("techtree/job_telepatia.html").replace("prose", "plain")
    (page,) = run_search(TechTree(), router(routes))
    assert page == []
