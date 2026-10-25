from collections.abc import Callable
from typing import Any

import pytest
from boards_util import router, run_search

from linkit_all.core.search import SearchConfig
from linkit_all.sources.boards.work180 import Work180

AU_JOB = "/en-au/for-women/employer/transgrid/job/1083968/"


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "/en-au/jobs-sitemap.xml": load_fixture("work180/sitemap_au.xml"),
        AU_JOB: load_fixture("work180/detail_au.html"),
        "/job/21552/": (404, "gone"),
        "/job/1071913/": (404, "gone"),
    }


def test_region_sitemap_then_posting_pages(load_fixture: Callable[[str], Any]) -> None:
    calls: list[Any] = []
    pages = run_search(Work180(), router(_routes(load_fixture), calls), board="au")
    (job,) = [
        s for p in pages for s in p
    ]  # the other postings answer 404; search pages are no jobs
    assert job.title == "Manager, Business Improvement and Strategic Initiatives"
    assert job.company == "Transgrid" and job.location == "Sydney, NSW, Australia"
    assert (
        job.url
        == "https://work180.com/en-au/for-women/employer/transgrid/job/1083968/manager-business-improvement-and-strategic-in"
    )
    assert job.extra["id"] == "1083968" and job.extra["employer"] == "transgrid"
    # the employer's own apply page, as the flight data states it
    assert (
        job.apply_url
        == "https://careers.transgrid.com.au/job/Sydney-Manager%2C-Business-Improvement-and-Strategic-Initiatives/1368929566/"
    )
    assert job.ats == "work180"
    assert "LUMEA" in job.description and "<" not in job.description
    assert job.posted_at is not None and (job.posted_at.month, job.posted_at.day) == (10, 16)
    ids = [r.url.path.split("/job/")[1].split("/")[0] for r in calls if "/job/" in r.url.path]
    assert ids == sorted(ids, key=int, reverse=True)  # newest posting first
    assert not any("/search/" in r.url.path for r in calls)


def test_expired_posting_and_non_external_apply(load_fixture: Callable[[str], Any]) -> None:
    page = load_fixture("work180/detail_au.html")
    routes = _routes(load_fixture)
    routes[AU_JOB] = page.replace('\\"expired\\":null', '\\"expired\\":\\"2026-10-17T00:00:00Z\\"')
    assert [s for p in run_search(Work180(), router(routes), board="au") for s in p] == []
    routes[AU_JOB] = page.replace(
        '\\"applicationType\\":\\"EXTERNAL\\"', '\\"applicationType\\":\\"EMAIL\\"'
    )
    (job,) = [s for p in run_search(Work180(), router(routes), board="au") for s in p]
    assert job.apply_url == job.url


def test_posting_id_must_match_the_url(load_fixture: Callable[[str], Any]) -> None:
    routes = _routes(load_fixture)
    routes[AU_JOB] = load_fixture("work180/detail_au.html").replace(
        '"value":"1083968"', '"value":"7"'
    )
    assert [s for p in run_search(Work180(), router(routes), board="au") for s in p] == []


def test_remote_posting_page_has_a_telecommute_flag(load_fixture: Callable[[str], Any]) -> None:
    sitemap = (
        "<urlset><url><loc>https://work180.com/en-us/for-women/employer/comparative/job/535122/x</loc>"
        "<lastmod>2026-10-01</lastmod></url></urlset>"
    )
    routes = {
        "/en-us/jobs-sitemap.xml": sitemap,
        "/job/535122/": load_fixture("work180/detail_us_remote.html"),
    }
    (job,) = [s for p in run_search(Work180(), router(routes), board="us") for s in p]
    assert job.remote == "remote" and job.company == "Comparative"
    assert (
        job.apply_url
        == "https://careers.comparative.ai/jobs/1544181-senior-software-developer-full-stack"
    )
    assert job.ats == "teamtailor"  # /jobs/<id>-<slug> on a custom domain is Teamtailor's shape


def test_resume_unknown_region_and_tasks(load_fixture: Callable[[str], Any]) -> None:
    assert run_search(Work180(), router(_routes(load_fixture)), board="au", start_page=1) == []
    with pytest.raises(ValueError, match="unknown region"):
        run_search(Work180(), router({}), board="zz")
    cfg = SearchConfig.model_validate({"search": {"queries": ["a"], "max_results_per_query": 500}})
    tasks = Work180().tasks(cfg)
    assert [t.board for t in tasks] == ["au", "uk", "us"]
    assert all(t.limit == 120 for t in tasks)  # the site's Crawl-delay caps one run
