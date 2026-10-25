import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators import remoteok
from linkit_all.sources.aggregators.remoteok import RemoteOK


def _ok(data):
    return lambda req: httpx.Response(200, json=data)


def test_search_skips_the_legal_notice_and_maps_postings(search_pages, load_fixture):
    feed = load_fixture("remoteok/feed.json")
    assert "legal" in feed[0]
    calls: list[str] = []
    ((first, second, third),) = search_pages(RemoteOK(), _ok(feed), calls=calls)
    assert calls == [remoteok.API]
    assert (first.title, first.company) == (
        "Sales Development Representative German Speaking",
        "Huzzle",
    )
    # the job URL stays on remoteok.com: the API terms ask for a link back
    assert (
        first.url.startswith("https://remoteOK.com/remote-jobs/") and first.apply_url == first.url
    )
    assert first.remote == "remote" and first.extra == {"id": "1137563"}
    assert first.posted_at is not None and first.posted_at.isoformat() == "2026-10-23T16:00:18"
    assert first.salary_min is None and "<" not in first.description
    assert second.company == "B2spin" and third.company == "Huzzle"


def test_a_stated_salary_is_yearly_usd(search_pages, load_fixture):
    feed = load_fixture("remoteok/feed.json")
    feed[1]["salary_min"], feed[1]["salary_max"] = 80000, 120000
    ((first, *_),) = search_pages(RemoteOK(), _ok(feed))
    assert (first.salary_min, first.salary_max) == (80000, 120000)
    assert (first.salary_currency, first.salary_interval) == ("USD", "year")


def test_limit_resume_and_rows_without_a_company(search_pages, load_fixture):
    feed = load_fixture("remoteok/feed.json")
    assert len(search_pages(RemoteOK(), _ok(feed), limit=2)[0]) == 2
    assert search_pages(RemoteOK(), _ok(feed), start_page=1) == []
    feed[1]["company"] = ""
    assert len(search_pages(RemoteOK(), _ok(feed))[0]) == 2


def test_it_is_an_opt_in_aggregator_with_one_feed_task():
    source = registry()["remoteok"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a", "b"]}, "sources": {"enabled": ["remoteok"]}}
    )
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1
    assert "link" in (remoteok.__doc__ or "")  # the attribution note stays in the module docstring
