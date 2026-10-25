from collections.abc import Callable
from typing import Any

from boards_util import router, run_details, run_search

from linkit_all.sources.base import JobStub
from linkit_all.sources.boards.nodesk import NoDesk


def test_feed_is_split_into_title_and_company(load_fixture: Callable[[str], Any]) -> None:
    feed = load_fixture("nodesk/index.xml")
    pages = run_search(NoDesk(), router({"index.xml": feed}))
    assert len(pages) == 1 and len(pages[0]) == 1  # the title without " at " is dropped
    job = pages[0][0]
    assert (job.title, job.company) == ("Senior Backend Engineer", "Skylight")
    assert job.url == "https://nodesk.co/remote-jobs/skylight-senior-backend-engineer/"
    assert job.description == "Join today\u2019s team."
    assert job.remote == "remote" and job.location == "Remote" and job.ats == "nodesk"
    assert job.posted_at is not None and (job.posted_at.month, job.posted_at.day) == (8, 6)
    assert job.posted_at.hour == 6  # 08:00 +0200
    assert search_resume_is_empty(feed)


def search_resume_is_empty(feed: str) -> bool:
    return run_search(NoDesk(), router({"index.xml": feed}), start_page=1) == []


def test_details_read_the_json_ld_description(load_fixture: Callable[[str], Any]) -> None:
    stub = JobStub(
        source="nodesk", url="https://nodesk.co/remote-jobs/x/", title="t", company="c",
        description="teaser",
    )  # fmt: skip
    page = load_fixture("nodesk/posting.html")
    assert (
        run_details(NoDesk(), router({"/x/": page}), stub).description == "Own the Rails monolith."
    )
    assert run_details(NoDesk(), router({"/x/": "<html></html>"}), stub).description == "teaser"
