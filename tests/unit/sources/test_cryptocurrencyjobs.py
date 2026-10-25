from collections.abc import Callable
from typing import Any

from boards_util import router, run_details, run_search

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.boards.cryptocurrencyjobs import CryptocurrencyJobs


def test_feed_is_split_into_title_and_company(load_fixture: Callable[[str], Any]) -> None:
    feed = load_fixture("cryptocurrencyjobs/index.xml")
    pages = run_search(CryptocurrencyJobs(), router({"index.xml": feed}))
    assert len(pages) == 1 and len(pages[0]) == 2  # the title without " at " is dropped
    first, second = pages[0]
    assert (first.title, first.company) == ("Senior Platform Engineer", "Chronicle")
    assert first.url.endswith("/chronicle-senior-platform-engineer/")
    assert first.description == "Join today\u2019s team."  # &rsquo; outside CDATA still parses
    assert (
        first.location == "Remote"
        and first.remote == "remote"
        and first.ats == "cryptocurrencyjobs"
    )
    assert first.posted_at is not None and first.posted_at.hour == 14  # +0200 -> UTC
    assert first.extra == {"id": first.url}
    # "(Singapore only)" marks an on-site role
    assert second.title == "Compliance Analyst" and second.company == "Acme Exchange"
    assert second.location == "Singapore" and second.remote == "onsite"


def test_feed_is_not_paged_and_obeys_limit(load_fixture: Callable[[str], Any]) -> None:
    routes = {"index.xml": load_fixture("cryptocurrencyjobs/index.xml")}
    assert run_search(CryptocurrencyJobs(), router(routes), start_page=1) == []
    (page,) = run_search(CryptocurrencyJobs(), router(routes), limit=1)
    assert len(page) == 1


def test_details_read_the_json_ld_description(load_fixture: Callable[[str], Any]) -> None:
    stub = JobStub(
        source="cryptocurrencyjobs", url="https://cryptocurrencyjobs.co/x/", title="t", company="c",
        description="teaser",
    )  # fmt: skip
    page = load_fixture("cryptocurrencyjobs/posting.html")
    full = run_details(CryptocurrencyJobs(), router({"cryptocurrencyjobs.co/x/": page}), stub)
    assert "platform stack." in full.description and "Rust and Go." in full.description
    assert "<" not in full.description
    # a page without a posting keeps the feed's text
    kept = run_details(CryptocurrencyJobs(), router({"/x/": "<html></html>"}), stub)
    assert kept.description == "teaser"


def test_task_is_one_recent_feed() -> None:
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a", "b"], "max_results_per_query": 50}}
    )
    source = CryptocurrencyJobs()
    assert source.kind == "board" and not source.is_enabled(cfg)
    cfg.sources.enabled = ["cryptocurrencyjobs"]
    assert source.is_enabled(cfg)
    (task,) = source.tasks(cfg)
    assert task.limit == 100
