from collections.abc import Callable
from typing import Any

from boards_util import router, run_search

from linkit_all.sources.boards.weworkremotely import WeWorkRemotely


def test_feed_splits_company_and_title(load_fixture: Callable[[str], Any]) -> None:
    routes = {"remote-jobs.rss": load_fixture("weworkremotely/remote-jobs.rss")}
    pages = run_search(WeWorkRemotely(), router(routes))
    assert len(pages) == 1 and len(pages[0]) == 1  # the title with no "Company: " is dropped
    job = pages[0][0]
    assert (job.company, job.title) == ("Proxify AB", "Senior Fullstack Developer (Python)")
    assert job.url.endswith("/proxify-ab-senior-fullstack-developer-python-3")
    assert job.extra == {"id": "proxify-ab-senior-fullstack-developer-python-3"}
    assert job.location == "Anywhere in the World" and job.remote == "remote"
    assert job.description == "Join us.\n\nPython" or (
        "Join us." in job.description and "<" not in job.description
    )
    assert job.posted_at is not None and (job.posted_at.month, job.posted_at.day) == (6, 17)
    assert job.ats == "weworkremotely"


def test_feed_is_not_paged(load_fixture: Callable[[str], Any]) -> None:
    routes = {"remote-jobs.rss": load_fixture("weworkremotely/remote-jobs.rss")}
    assert run_search(WeWorkRemotely(), router(routes), start_page=1) == []


def test_text_that_is_no_feed_yields_nothing() -> None:
    (page,) = run_search(WeWorkRemotely(), router({"remote-jobs.rss": "<html>not a feed"}))
    assert page == []
