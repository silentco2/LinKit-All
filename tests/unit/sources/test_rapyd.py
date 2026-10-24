import httpx
import pytest

from linkit_all.sources.ats.rapyd import Rapyd
from linkit_all.sources.ats_detector import detect

HOST = "www.rapyd.net"


def _handler(load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/company/careers-search/":
            return httpx.Response(200, text=load_fixture("rapyd/listing.html"))
        if path == "/company/careers/positions/finance-data-developer-bogota-colombia/":
            return httpx.Response(200, text=load_fixture("rapyd/position.html"))
        return httpx.Response(404)

    return handler


def test_search_follows_position_links(search_pages, load_fixture):
    pages = search_pages(Rapyd(), _handler(load_fixture), board=HOST)
    assert len(pages) == 1 and len(pages[0]) == 1  # the noc-manager page is gone; nav links skipped
    job = pages[0][0]
    assert (job.title, job.company, job.location) == (
        "Finance Data Analyst",
        "Rapyd",
        "Bogota, Colombia",
    )
    assert (
        job.url
        == f"https://{HOST}/company/careers/positions/finance-data-developer-bogota-colombia/"
    )
    assert job.extra["id"] == "finance-data-developer-bogota-colombia" and job.ats == "rapyd"
    assert "pipelines" in job.description and "Python" in job.description
    assert "Partners" not in job.description  # the footer is outside the content column
    assert job.remote is None


def test_remote_comes_from_the_location_only(search_pages, load_fixture):
    html = load_fixture("rapyd/position.html").replace(
        "Bogota, Colombia</h4>", "Remote, Israel</h4>"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/company/careers-search/":
            return httpx.Response(200, text=load_fixture("rapyd/listing.html"))
        return httpx.Response(200, text=html)

    assert search_pages(Rapyd(), handler, board=HOST)[0][0].remote == "remote"


def test_board_must_be_a_host(search_pages):
    with pytest.raises(ValueError, match="not a careers host"):
        search_pages(Rapyd(), lambda req: httpx.Response(404), board="rapyd")


def test_url_patterns():
    url = "https://www.rapyd.net/company/careers/positions/sales-manager-bogota-colombia/"
    assert detect(url) == ("rapyd", HOST)
    assert detect("rapyd:www.rapyd.net") == ("rapyd", HOST)
