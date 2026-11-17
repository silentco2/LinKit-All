import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.wp_job_manager import WpJobManager
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def test_search_reads_the_plugins_feed(search_pages, load_fixture):
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(str(req.url))
        return httpx.Response(200, text=load_fixture("wp-job-manager/feed.xml"))

    ((a, b),) = search_pages(WpJobManager(), handler, board="jobs.coastline.example", calls=None)
    assert calls == [
        "https://jobs.coastline.example/?feed=job_feed&posts_per_page=100"
    ]  # short page
    assert (a.title, a.company, a.location) == (
        "Marine Biologist",
        "Reefwatch Trust",
        "Galway, Ireland",
    )
    assert a.url == "https://jobs.coastline.example/job/marine-biologist/"
    assert "Study the" in a.description and "reef" in a.description
    assert (b.company, b.remote) == ("Coastline", "remote")  # no employer named: the site's name


def test_a_site_without_the_feed_fails_loudly(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404)
            if req.url.path == "/robots.txt"
            else httpx.Response(200, text="<html>")
        )

    with pytest.raises(ValueError, match="no job feed"):
        search_pages(WpJobManager(), handler, board="jobs.coastline.example")


def test_shorthand():
    assert detect("wp-job-manager:jobs.coastline.example") == (
        "wp-job-manager",
        "jobs.coastline.example",
    )
