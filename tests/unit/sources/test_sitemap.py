import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.sitemap import Sitemap, slug_title
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


BOARD = "https://careers.fernway.example/sitemap.xml"


def _serve(load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        files = {
            "/sitemap.xml": "sitemap/index.xml",
            "/sitemap-jobs.xml": "sitemap/jobs.xml",
            "/jobs/4412/data-analyst": "sitemap/detail.html",
        }
        if req.url.host == "careers.fernway.example" and req.url.path in files:
            return httpx.Response(200, text=load_fixture(files[req.url.path]))
        return httpx.Response(404)

    return handler


def test_search_keeps_posting_paths_newest_first(search_pages, load_fixture):
    ((a, b),) = search_pages(Sitemap(), _serve(load_fixture), board=BOARD)
    assert (a.title, a.company) == ("Data Analyst", "Fernway")
    assert (
        a.url == "https://careers.fernway.example/jobs/4412/data-analyst"
        and a.extra["id"] == "4412"
    )
    assert b.title == "Platform Engineer"


def test_fetch_details_reads_the_posting(search_pages, fetch_details, load_fixture):
    stub = search_pages(Sitemap(), _serve(load_fixture), board=BOARD)[0][0]
    full = fetch_details(Sitemap(), _serve(load_fixture), stub)
    assert (full.title, full.company, full.location) == (
        "Data Analyst (Payments)",
        "Fernway Ltd",
        "Leeds, GB",
    )
    assert full.description == "Read the numbers." and full.posted_at is not None


def test_slug_title_and_shorthand():
    assert slug_title("https://x/jobs/77/senior_ml-engineer.html") == "Senior Ml Engineer"
    assert detect(f"sitemap:{BOARD}") == ("sitemap", BOARD)
