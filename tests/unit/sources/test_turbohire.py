import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.turbohire import TurboHire
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http

ORG = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture, org_status=200):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "thapi.azurewebsites.net"
        if req.url.path == "/api/token/noauth":
            assert req.headers["origin"] == "https://northwind.turbohire.co"
            assert req.headers["referer"] == "https://northwind.turbohire.co/"
            return httpx.Response(200, json={"access_token": "anon-token"})
        assert req.headers["authorization"] == "Bearer anon-token"
        if req.url.path == "/api/publicorganizations":
            assert req.url.params["accountName"] == "northwind"
            return httpx.Response(org_status, json={"OrgID": ORG})
        assert req.method == "POST" and req.url.path == "/api/careerpagev2/filteredjobs"
        assert req.url.params["orgId"] == ORG and req.url.params["pageType"] == "0"
        return httpx.Response(200, json=load_fixture("turbohire/jobs.json"))

    return handler


def test_search_makes_the_pages_three_requests(search_pages, load_fixture):
    ((a, b),) = search_pages(TurboHire(), _serve(load_fixture), board="northwind")
    assert (a.title, a.company) == ("Sales & Ops Lead", "Northwind")  # a hidden client is not named
    assert a.location == "Pune, India; Remote" and a.remote == "remote"
    assert a.url == "https://northwind.turbohire.co/job/publicjobs/ab12cd"
    assert a.description == "Lead sales." and a.extra["code"] == "TH-7"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-09T06:30:00"
    assert (b.company, b.location) == ("Saffron Kitchens", "Goa")


def test_an_unknown_tenant_is_reported(search_pages, load_fixture):
    with pytest.raises(Unsupported, match="no tenant"):
        search_pages(TurboHire(), _serve(load_fixture, org_status=404), board="northwind")


def test_url_patterns():
    assert detect("https://northwind.turbohire.co/job/publicjobs/ab12cd") == (
        "turbohire",
        "northwind",
    )
    assert detect("https://app.turbohire.co/login") is None
