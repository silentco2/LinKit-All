import httpx
import pytest

from linkit_all.sources.ats.adpmyjobs import AdpMyJobs
from linkit_all.sources.ats_detector import detect


def make_handler(load_fixture, seen: list[httpx.Request], site_status: int = 200):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "/career-site/" in req.url.path:
            if site_status != 200:
                return httpx.Response(site_status)
            return httpx.Response(200, json=load_fixture("adpmyjobs/site.json"))
        if req.url.path.endswith("/job-requisitions/5001"):
            return httpx.Response(200, json=load_fixture("adpmyjobs/detail.json"))
        return httpx.Response(200, json=load_fixture("adpmyjobs/list.json"))

    return handler


def test_search_resolves_orgoid_then_lists(search_pages, load_fixture):
    seen: list[httpx.Request] = []
    pages = search_pages(
        AdpMyJobs(), make_handler(load_fixture, seen), board="stellantisexternalcx"
    )
    (stub,) = pages[0]
    assert stub.title == "Sr. SQE"
    assert stub.company == "Stellantis"
    assert stub.url == "https://myjobs.adp.com/stellantisexternalcx/cx/job/5001"
    assert stub.ats == "adpmyjobs" and stub.extra["id"] == "5001"
    # the career-site call learns the orgoid; every listing call must carry it
    assert "orgoid" not in seen[0].headers
    assert seen[1].headers["orgoid"] == "G2QKPTS5DSF914GQ"
    assert seen[1].url.params["$top"] == "50"


def test_search_without_an_orgoid_fails(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"clientName": "X"})

    with pytest.raises(ValueError, match="orgoid"):
        search_pages(AdpMyJobs(), handler, board="x")


def test_fetch_details_rebuilds_from_the_url(fetch_details, load_fixture):
    seen: list[httpx.Request] = []
    source = AdpMyJobs()
    base = source.stub(
        {"reqId": "5001", "jobTitle": "Sr. SQE"}, "stellantisexternalcx", "Stellantis"
    )
    stub = fetch_details(source, make_handler(load_fixture, seen), base)
    assert "quality" in stub.description and "x()" not in stub.description
    assert stub.location == "Auburn Hills, Michigan, United States"
    assert stub.posted_at is not None and stub.posted_at.year == 2026
    assert seen[-1].headers["orgoid"] == "G2QKPTS5DSF914GQ"


def test_url_patterns():
    sources = [AdpMyJobs()]
    assert detect("https://myjobs.adp.com/stellantisexternalcx/cx/job/5001", sources) == (
        "adpmyjobs",
        "stellantisexternalcx",
    )
    api = "https://myjobs.adp.com/public/staffing/v1/career-site/jsmcareers"
    assert detect(api, sources) == ("adpmyjobs", "jsmcareers")
    assert detect("https://myjobs.adp.com/public/other", sources) is None
