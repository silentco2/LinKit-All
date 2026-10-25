from collections.abc import Callable
from typing import Any

from boards_util import router, run_search

from linkit_all.sources.boards.jobspresso import Jobspresso


def test_feed_maps_the_item(load_fixture: Callable[[str], Any]) -> None:
    calls: list[Any] = []
    routes = {"jobspresso.co/feed/": load_fixture("jobspresso/feed.xml")}
    pages = run_search(Jobspresso(), router(routes, calls))
    assert any("post_type=job_listing" in str(r.url) for r in calls)
    assert len(pages) == 1 and len(pages[0]) == 1  # the item with no employer is dropped
    job = pages[0][0]
    assert job.extra == {"id": "163363"}  # the guid's p= parameter
    assert (
        job.url
        == "https://jobspresso.co/job/wet-germany-various-mitarbeiter-in-fur-datenanalysen-remote/"
    )
    assert job.title == "Mitarbeiter/in (m/w/d) für Datenanalysen | Remote"
    assert job.company == "WET Beratungs- und Beteiligungsgesellschaft mbH"
    assert job.location == "Germany , Austria, Luxemburg"
    # the full content:encoded body wins over the short description
    assert "Komplett remote" in job.description and "Minijob" not in job.description
    assert job.remote == "remote" and job.ats == "jobspresso"
    assert job.posted_at is not None and (job.posted_at.month, job.posted_at.day) == (7, 16)


def test_feed_is_not_paged(load_fixture: Callable[[str], Any]) -> None:
    routes = {"jobspresso.co/feed/": load_fixture("jobspresso/feed.xml")}
    assert run_search(Jobspresso(), router(routes), start_page=1) == []


def test_blocked_feed_raises() -> None:
    import httpx
    import pytest

    with pytest.raises(httpx.HTTPStatusError):
        run_search(Jobspresso(), router({"jobspresso.co": (403, "no")}))
