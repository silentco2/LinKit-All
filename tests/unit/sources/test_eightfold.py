import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.eightfold import Eightfold
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def test_search_reads_the_v2_api(search_pages, load_fixture):
    data = load_fixture("eightfold/jobs.json")
    calls: list[str] = []
    ((a, b),) = search_pages(
        Eightfold(), lambda req: httpx.Response(200, json=data), board="northwind", calls=calls
    )
    assert calls == ["https://northwind.eightfold.ai/api/apply/v2/jobs?start=0&num=10"]
    assert (a.title, a.company) == ("ML Engineer", "Northwind")
    assert a.location == "Berlin, Germany; Remote" and a.remote == "remote"
    assert a.url == "https://northwind.eightfold.ai/careers/job/5501"
    assert a.extra == {"board": "northwind", "id": "5501", "req": "R-12"}
    assert a.posted_at is not None
    assert b.title == "Data Steward"
    assert b.url == "https://northwind.eightfold.ai/careers?pid=5502"  # no canonical link


def test_a_migrated_tenant_falls_back_to_pcsx(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/apply/v2/jobs":
            return httpx.Response(403, json={"message": "Not authorized for PCSX"})
        return httpx.Response(200, json=load_fixture("eightfold/pcsx.json"))

    calls: list[str] = []
    ((job,),) = search_pages(Eightfold(), handler, board="acme/acme.com", calls=calls)
    assert calls[1] == "https://acme.eightfold.ai/api/pcsx/search?domain=acme.com&start=0&num=10"
    assert (job.title, job.location) == ("Designer", "Paris")
    assert job.url == "https://acme.eightfold.ai/careers/job/7" and job.extra["req"] == "A7"


def test_fetch_details_reads_the_posting_record(fetch_details, load_fixture):
    stub = Eightfold.stub(load_fixture("eightfold/jobs.json")["positions"][0], "northwind")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json={"job_description": "<p>Do ML.</p>"})

    assert fetch_details(Eightfold(), handler, stub).description == "Do ML."
    assert seen == ["/api/apply/v2/jobs/5501"]


def test_url_patterns():
    url = "https://northwind.eightfold.ai/careers?query=x&domain=northwind.com"
    assert detect(url) == ("eightfold", "northwind/northwind.com")
    assert detect("https://northwind.eightfold.ai/careers") == ("eightfold", "northwind")
    assert detect("https://www.eightfold.ai/") is None
