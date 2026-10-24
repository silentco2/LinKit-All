from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.dover import Dover
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

CLIENT = "72c2afbf-36e4-4eec-8d78-5d2600498018"
JOB = "f9fd123e-e7ff-4bcc-a16a-bb8c47e591b5"


def test_search_lists_published_jobs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    slug, jobs = load_fixture("dover/slug.json"), load_fixture("dover/jobs.json")
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/careers-page-slug/qompyl"):
            return httpx.Response(200, json=slug)
        assert req.url.path.endswith(f"/careers-page/{CLIENT}/jobs")
        return httpx.Response(200, json=jobs)

    pages = search_pages(Dover(), handler, board="qompyl", calls=calls)
    assert len(pages) == 1
    cloud, office = pages[0]  # the sample and the unpublished posting are dropped
    assert cloud.title == "Cloud Infra Engineer" and cloud.company == "Qompyl"
    assert cloud.url == f"https://app.dover.com/apply/qompyl/{JOB}"
    assert cloud.location == "Brazil; International" and cloud.remote == "remote"
    assert cloud.extra == {"board": "qompyl", "id": JOB} and cloud.ats == "dover"
    assert office.remote == "onsite" and office.location == ""
    assert "limit=300" in calls[-1] and "offset=0" in calls[-1]


def test_paging_and_resume(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def item(n: int) -> dict[str, Any]:
        return {"id": f"j{n}", "title": f"Job {n}", "is_published": True, "is_sample": False}

    offsets: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if "careers-page-slug" in req.url.path:
            return httpx.Response(200, json={"id": CLIENT})
        offset = int(req.url.params["offset"])
        offsets.append(req.url.params["offset"])
        size = 300 if offset == 0 else 2
        results = [item(offset + n) for n in range(size)]
        return httpx.Response(200, json={"count": 302, "results": results})

    pages = search_pages(Dover(), handler, board="big")
    assert [len(p) for p in pages] == [300, 2] and offsets == ["0", "300"]
    assert pages[0][0].company == "Big"  # no name in the slug response: from the slug
    offsets.clear()
    resumed = search_pages(Dover(), handler, board="big", start_page=1)
    assert [len(p) for p in resumed] == [2] and offsets == ["300"]


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    detail = load_fixture("dover/detail.json")
    stub = JobStub(
        source="dover", url=f"https://app.dover.com/apply/qompyl/{JOB}", title="t", company="c"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith(f"/inbound/application-portal-job/{JOB}")
        return httpx.Response(200, json=detail)

    full = fetch_details(Dover(), handler, stub)
    assert full.description.startswith("Do things") and "alert" not in full.description
    assert "equity" in full.description and "visa" in full.description
    assert (full.salary_min, full.salary_max, full.salary_currency) == (80000, 120000, "USD")
    assert full.salary_interval == "year" and full.extra["employment"] == "full-time"

    detail["compensation"]["open_to_sharing_comp"] = False
    private = fetch_details(Dover(), handler, stub)
    assert private.salary_min is None and private.description  # pay stays unpublished


def test_url_patterns() -> None:
    assert detect(f"https://app.dover.com/apply/qompyl/{JOB}") == ("dover", "qompyl")
    assert detect("https://app.dover.com/jobs/qompyl") == ("dover", "qompyl")
    assert detect("dover:qompyl") == ("dover", "qompyl")
