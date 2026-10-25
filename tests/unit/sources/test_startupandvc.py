from collections.abc import Callable
from typing import Any

from boards_util import router, run_search

from linkit_all.sources.boards.startupandvc import StartupAndVC


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "/venture-capital-jobs/associate-9a2fb": load_fixture("startupandvc/associate-9a2fb.html"),
        "/venture-capital-jobs/analyst-39b3f": load_fixture("startupandvc/analyst-39b3f.html"),
        "/venture-capital-jobs": load_fixture("startupandvc/listing.html"),
    }


def test_listing_then_vacancy_pages(load_fixture: Callable[[str], Any]) -> None:
    calls: list[Any] = []
    pages = run_search(StartupAndVC(), router(_routes(load_fixture), calls))
    assert len(pages) == 1 and len(pages[0]) == 2  # duplicate anchors and nav links are ignored
    assoc, analyst = pages[0]
    assert (assoc.title, assoc.company) == ("Associate", "B Capital Group")
    assert assoc.location == "New York, USA"
    # the board page is the stable url; "Apply now" (tracking tail removed) is the apply url
    assert assoc.url == "https://www.startupandvc.com/venture-capital-jobs/associate-9a2fb"
    assert assoc.apply_url == "https://www.linkedin.com/jobs/view/4417182287/?eBP=xyz&trk=abc"
    assert assoc.ats == "startupandvc"  # LinkedIn is not an ATS we apply through
    assert "Real body with detail" in assoc.description and "alert" not in assoc.description
    assert "is looking for" not in assoc.description  # the rich body beats the ld+json stub
    assert assoc.posted_at is not None and (assoc.posted_at.month, assoc.posted_at.day) == (7, 7)
    assert assoc.extra["id"] == "associate-9a2fb"
    # an employer's own ATS link names the ATS
    assert analyst.ats == "greenhouse" and analyst.apply_url == (
        "https://boards.greenhouse.io/indexventures/jobs/4412345"
    )


def test_missing_vacancy_page_is_skipped_and_resume_skips_chunks(
    load_fixture: Callable[[str], Any],
) -> None:
    routes = _routes(load_fixture)
    routes["/venture-capital-jobs/analyst-39b3f"] = (404, "gone")
    (page,) = run_search(StartupAndVC(), router(routes))
    assert [s.title for s in page] == ["Associate"]
    assert run_search(StartupAndVC(), router(_routes(load_fixture)), start_page=1) == []
    (limited,) = run_search(StartupAndVC(), router(_routes(load_fixture)), limit=1)
    assert [s.title for s in limited] == ["Associate"]
