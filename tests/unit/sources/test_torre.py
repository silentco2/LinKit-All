from collections.abc import Callable
from typing import Any

from boards_util import router, run_search

from linkit_all.sources.boards.torre import Torre


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    en = load_fixture("torre/sitemap-en-1656.xml")
    return {
        "torre.ai/sitemap-index.xml": load_fixture("torre/sitemap-index.xml"),
        "sitemap-en-1656.xml": en,
        "sitemap-es-155.xml": load_fixture("torre/sitemap-es-155.xml"),
        "sitemap--2.xml": (404, "retired"),
        "post/KWN1DZKr-": load_fixture("torre/post_remote.html"),
        "post/xWpM2kAw-": load_fixture("torre/post_onsite.html"),
        "post/kWR9eKQr-": load_fixture("torre/post_escaped.html"),
        "post/qdPeQ9Pr-": load_fixture("torre/post_closed.html"),
    }


def _by_id(pages: list[list[Any]]) -> dict[str, Any]:
    return {s.extra["id"]: s for p in pages for s in p}


def test_sitemaps_then_posting_pages(load_fixture: Callable[[str], Any]) -> None:
    calls: list[Any] = []
    pages = run_search(Torre(), router(_routes(load_fixture), calls))
    jobs = _by_id(pages)
    # two postings have no page (404) and the closed one has no JobPosting; the post that sits
    # in two sitemaps is fetched once
    assert set(jobs) == {"KWN1DZKr", "xWpM2kAw", "kWR9eKQr"}
    assert sum(1 for r in calls if "post/KWN1DZKr" in str(r.url)) == 1

    onsite = jobs["xWpM2kAw"]
    assert (onsite.title, onsite.company) == ("Mechanical Design Engineer", "ViisGlobal")
    assert onsite.location == "Butte, Montana, United States"  # a street that is a place name
    assert onsite.url.startswith("https://torre.ai/post/xWpM2kAw") and onsite.ats == "torre"
    assert (onsite.salary_min, onsite.salary_max) == (90000, 130000)
    assert (onsite.salary_currency, onsite.salary_interval) == ("USD", "year")
    assert "SolidWorks" in onsite.description and "Bachelor\u2019s" in onsite.description
    assert onsite.posted_at is not None and (onsite.posted_at.month, onsite.posted_at.day) == (
        9,
        18,
    )

    remote = jobs["KWN1DZKr"]
    assert remote.remote == "remote" and remote.location.startswith("Remote, ")
    assert (remote.salary_min, remote.salary_max) == (None, None)  # the 1-1000 placeholder

    # a description whose markup is escaped twice still reads as text
    escaped = jobs["kWR9eKQr"]
    assert "Blue Recruitment Personnel is recruiting" in escaped.description
    assert "&lt;" not in escaped.description and "<p>" not in escaped.description
    assert (escaped.salary_min, escaped.salary_max, escaped.salary_interval) == (16, 18, "hour")


def test_resume_and_limit(load_fixture: Callable[[str], Any]) -> None:
    assert run_search(Torre(), router(_routes(load_fixture)), start_page=1) == []
    (limited,) = run_search(Torre(), router(_routes(load_fixture)), limit=2)
    assert len(limited) <= 2


def test_gone_sitemap_is_skipped_but_other_errors_raise(load_fixture: Callable[[str], Any]) -> None:
    import httpx
    import pytest

    routes = _routes(load_fixture)
    routes["sitemap-es-155.xml"] = (403, "blocked")
    with pytest.raises(httpx.HTTPStatusError):
        run_search(Torre(), router(routes))
