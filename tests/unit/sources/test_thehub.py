from collections.abc import Callable
from typing import Any

from boards_util import router, run_search

from linkit_all.sources.boards.thehub import TheHub


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "thehub.io/sitemap.xml": load_fixture("thehub/sitemap.xml"),
        "thehub.io/sitemap-jobs.xml": load_fixture("thehub/sitemap-jobs.xml"),
        "/jobs/5f1b2c3d4e5f6a7b8c9d0e1f": load_fixture("thehub/job_5f1b.html"),
        "/jobs/aaaaaaaaaaaa00000000bbbb": load_fixture("thehub/job_aaaa.html"),
    }


def test_index_then_jobs_sitemap_then_pages(load_fixture: Callable[[str], Any]) -> None:
    calls: list[Any] = []
    pages = run_search(TheHub(), router(_routes(load_fixture), calls))
    assert len(pages) == 1
    newest, older = pages[0]  # newest lastmod first; the bare /jobs url is not a posting
    assert newest.title == "Remote Designer" and newest.company == "Pleo"
    assert older.url == "https://thehub.io/jobs/5f1b2c3d4e5f6a7b8c9d0e1f"
    assert (older.title, older.company) == ("Backend Engineer", "Lunar Bank")
    assert older.location == "Copenhagen, DK" and older.ats == "thehub"
    assert older.extra["id"] == "5f1b2c3d4e5f6a7b8c9d0e1f"
    # the escaped description is decoded into text
    assert "Build the" in older.description and "payments" in older.description
    assert "<" not in older.description and "&lt;" not in older.description
    assert older.posted_at is not None and (older.posted_at.month, older.posted_at.day) == (10, 2)
    assert not any(r.url.path == "/sitemap-companies.xml" for r in calls)


def test_no_jobs_sitemap_means_nothing_to_do(load_fixture: Callable[[str], Any]) -> None:
    index = load_fixture("thehub/sitemap.xml").replace("sitemap-jobs", "sitemap-other")
    assert run_search(TheHub(), router({"thehub.io/sitemap.xml": index})) == []


def test_resume_and_limit(load_fixture: Callable[[str], Any]) -> None:
    assert run_search(TheHub(), router(_routes(load_fixture)), start_page=1) == []
    (limited,) = run_search(TheHub(), router(_routes(load_fixture)), limit=1)
    assert [s.title for s in limited] == ["Remote Designer"]
