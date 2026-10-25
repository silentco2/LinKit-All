import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobtech import JobTech


def _handler(load_fixture, seen=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req.url.params["date"])
        return httpx.Response(200, json=load_fixture("jobtech/stream.json"))

    return handler


def test_search_maps_live_ads_newest_first(search_pages, load_fixture):
    seen: list[str] = []
    pages = search_pages(JobTech(), _handler(load_fixture, seen))
    assert len(seen) == 1 and [len(p) for p in pages] == [
        2
    ]  # removed and employer-less ads skipped
    live, older = pages[0]
    assert live.company == "Tatvanord"  # the trading name, not the numbered shell company
    assert (live.title, live.location) == (
        "Junior Test Automation Engineer", "Göteborg, Västra Götalands län, Sverige",
    )  # fmt: skip
    assert live.url == "https://arbetsformedlingen.se/platsbanken/annonser/31223446"
    assert live.description == "About the\nRole"  # script text is gone
    assert live.posted_at is not None and live.posted_at.day == 10
    assert (older.company, older.description) == ("Legal AB", "old")


def test_the_window_is_capped_and_the_task_limit_applies(search_pages, load_fixture):
    seen: list[str] = []
    pages = search_pages(JobTech(), _handler(load_fixture, seen), limit=1, posted_within_days=90)
    assert [s.company for p in pages for s in p] == ["Tatvanord"]
    from datetime import datetime, timedelta

    since = datetime.fromisoformat(seen[0])
    assert timedelta(days=6) < datetime.now() - since < timedelta(days=8)  # 7 days, not 90


def test_start_page_past_the_end_yields_nothing(search_pages, load_fixture):
    assert search_pages(JobTech(), _handler(load_fixture), start_page=1) == []


def test_it_is_an_opt_in_aggregator():
    assert registry()["jobtech"].kind == "aggregator"
