import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.flowxtra import Flowxtra


def test_search(search_pages, load_fixture):
    data = load_fixture("flowxtra/jobs.json")
    calls: list[str] = []
    ((a, b),) = search_pages(Flowxtra(), lambda req: httpx.Response(200, json=data), calls=calls)
    assert calls == ["https://app.flowxtra.com/api/central/jobs?status=Live&per_page=100&page=1"]
    assert (a.title, a.company, a.location) == ("QA Engineer", "Bluefin GmbH", "Vienna, Austria")
    assert a.url == "https://flowxtra.com/jobs/qa-engineer-77" and a.remote == "remote"
    assert a.extra == {"id": "77"}
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-10T08:00:00"
    assert b.remote is None and b.extra == {"id": "clerk-78"}
    assert len(search_pages(Flowxtra(), lambda r: httpx.Response(200, json=data), limit=1)[0]) == 1


def test_it_is_an_opt_in_feed():
    source = registry()["flowxtra"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate({"sources": {"enabled": ["flowxtra"]}})
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1
