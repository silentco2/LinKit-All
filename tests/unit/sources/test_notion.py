import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.notion import Notion
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


PAGE = "0123456789abcdef0123456789abcdef"


def test_a_page_of_child_pages(search_pages, load_fixture):
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://lumen.notion.site/api/v3/loadPageChunk"
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("notion/page.json"))

    ((a, b, c),) = search_pages(Notion(), handler, board=f"lumen/{PAGE}")
    assert sent[0]["pageId"] == "01234567-89ab-cdef-0123-456789abcdef"
    assert [s.title for s in (a, b, c)] == ["Founding Engineer", "Product Designer", "Ops Lead"]
    assert a.url == "https://lumen.notion.site/aaaaaaaa000000000000000000000001"
    assert a.company == "Lumen" and a.posted_at is not None


def test_a_database_board_applies_its_view(search_pages, load_fixture):
    queries: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("loadPageChunk"):
            return httpx.Response(200, json=load_fixture("notion/db_page.json"))
        queries.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("notion/rows.json"))

    ((job,),) = search_pages(Notion(), handler, board=f"lumen/{PAGE}")
    assert queries[0]["loader"]["filter"] == {"operator": "and", "filters": []}
    assert queries[0]["source"] == {"type": "collection", "id": "col1", "spaceId": "s1"}
    assert (job.title, job.location, job.remote) == ("Backend Engineer", "Remote, EU", "remote")


def test_a_private_page_fails_loudly(search_pages):
    with pytest.raises(ValueError, match="not public"):
        search_pages(
            Notion(),
            lambda r: httpx.Response(200, json={"recordMap": {"block": {}}}),
            board=f"x/{PAGE}",
        )


def test_url_patterns():
    assert detect(f"https://lumen.notion.site/Careers-{PAGE}") == ("notion", f"lumen/{PAGE}")
    assert detect(f"https://lumen.notion.site/{PAGE}?v=1") == ("notion", f"lumen/{PAGE}")
