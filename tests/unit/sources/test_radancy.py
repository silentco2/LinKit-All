import httpx
import pytest

from linkit_all.sources.ats import radancy
from linkit_all.sources.ats.radancy import Radancy, job_id, posted
from linkit_all.sources.ats_detector import detect

HOST = "careers.astrazeneca.com"


def _handler(load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("radancy/sitemap.xml"))
        job = path.rstrip("/").rsplit("/", 1)[-1]
        try:
            return httpx.Response(200, text=load_fixture(f"radancy/job_{job}.html"))
        except FileNotFoundError:
            return httpx.Response(404)

    return handler


def test_job_id_and_date():
    assert job_id(f"https://{HOST}/job/lafayette/regional-account-manager/43991/96556869600") == (
        "96556869600"
    )
    assert (
        job_id("https://careers.ing.com/en/job/bucharest/lead/3121/39724266176/") == "39724266176"
    )
    assert job_id("https://careers.ing.com/en/category/it-engineering-jobs/2618/32177152/1") == ""
    assert job_id("https://careers.ing.com") == ""
    assert posted("2026-6-17").isoformat() == "2026-06-17T00:00:00"  # type: ignore[union-attr]
    assert posted("2026-13-40") is None and posted(None) is None


def test_search_reads_the_sitemap_then_each_posting(search_pages, load_fixture):
    pages = search_pages(Radancy(), _handler(load_fixture), board=HOST)
    a, b = pages[0]
    assert (a.title, a.company, a.location) == (
        "Regional Account Manager",
        "AstraZeneca",
        "Lafayette, Louisiana, United States",
    )
    assert a.url == f"https://{HOST}/job/lafayette/regional-account-manager/43991/96556869600"
    assert a.extra["board"] == HOST and a.extra["id"] == "96556869600"
    assert "Sell things." in a.description and "alert" not in a.description
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-17T00:00:00"
    assert a.ats == "radancy" and a.remote is None
    # no organisation in the posting: the company comes from the host; "10" is not a region
    assert (b.title, b.company, b.location, b.remote) == (
        "Chapter Lead",
        "Astrazeneca",
        "Bucharest, RO",
        "remote",
    )


def test_resume_and_missing_postings(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(radancy, "PAGE", 1)
    pages = search_pages(Radancy(), _handler(load_fixture), board=HOST, start_page=1)
    assert [[s.title for s in p] for p in pages] == [["Chapter Lead"]]

    def gone(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("radancy/sitemap.xml"))
        return httpx.Response(404)

    assert search_pages(Radancy(), gone, board=HOST) == [
        [],
        [],
    ]  # a posting that is gone is skipped


def test_board_must_be_a_host(search_pages):
    with pytest.raises(ValueError, match="not a career-site host"):
        search_pages(Radancy(), lambda req: httpx.Response(404), board="astrazeneca")


def test_url_patterns():
    url = f"https://{HOST}/job/lafayette/regional-account-manager/43991/96556869600"
    assert detect(url) == ("radancy", HOST)
    assert detect("https://careers.ing.com/en/job/bucharest/lead/3121/39724266176") == (
        "radancy",
        "careers.ing.com",
    )
    assert detect("radancy:careers.ing.com") == ("radancy", "careers.ing.com")
