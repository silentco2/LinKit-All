import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.magneto import Magneto
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def test_search_reads_cards_and_stops_on_a_repeated_page(search_pages, load_fixture):
    html = load_fixture("magneto/search.html")
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text=html)
        )

    ((a, b),) = search_pages(Magneto(), handler, query="Tecnologia", calls=calls)
    pages = [c for c in calls if "robots" not in c]
    assert pages[0] == "https://www.magneto365.com/co/trabajos/buscar/tecnologia"
    assert len(pages) == 2 and pages[1].endswith("=2")  # page 2 brought nothing new
    assert (a.title, a.company, a.location) == (
        "Desarrollador Backend",
        "Cafetal Digital SAS",
        "Medellín",
    )
    assert a.url == "https://www.magneto365.com/co/empleos/desarrollador-backend-555001"
    assert a.extra == {"id": "555001"}
    assert (b.company, b.location) == ("Confidencial", "")  # a card's last line can be the pay
    assert b.url == "https://www.magneto365.com/co/empleos/analista-qa-555002"


def test_one_task_per_query_and_none_without():
    source = registry()["magneto"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {
            "search": {"queries": ["a", "b"], "locations": ["x", "y"]},
            "sources": {"enabled": ["magneto"]},
        }
    )
    assert len(source.tasks(cfg)) == 2 and source.tasks(SearchConfig()) == []
