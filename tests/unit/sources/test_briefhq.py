import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.briefhq import BriefHQ


def test_search_reads_the_inline_postings(search_pages, load_fixture):
    task = BriefHQ().tasks(SearchConfig())[0]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("briefhq/careers.html"))

    (page,) = search_pages(BriefHQ(), handler, board=task.board)
    onsite, remote = page  # the Organization and BreadcrumbList blocks are ignored
    assert onsite.title == "Product Builder (Forward Deployed)"
    assert onsite.company == "Brief"
    assert onsite.location == "San Francisco, CA, US"
    assert onsite.url == "https://briefhq.ai/careers/#product-builder-forward-deployed"
    assert onsite.extra["id"] == "product-builder-forward-deployed"
    assert onsite.remote is None
    assert "Ship product with customers." in onsite.description
    assert remote.remote == "remote"
    assert remote.url == "https://briefhq.ai/careers/#senior-product-builder-engineering"


def test_it_is_a_company_plugin_that_runs_only_when_enabled():
    source = registry()["briefhq"]
    assert source.kind == "company" and not source.url_patterns
    assert not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate({"sources": {"enabled": ["briefhq"]}})
    assert source.is_enabled(cfg)
