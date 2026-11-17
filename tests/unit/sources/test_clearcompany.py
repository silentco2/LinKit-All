import httpx

from linkit_all.sources.ats.clearcompany import ClearCompany
from linkit_all.sources.ats_detector import detect

GUID = "0a1b2c3d-1111-2222-3333-444455556666"


def test_search_stops_at_the_reported_total(search_pages, load_fixture):
    data = load_fixture("clearcompany/jobs.json")
    calls: list[str] = []
    pages = search_pages(
        ClearCompany(), lambda req: httpx.Response(200, json=data), board=GUID, calls=calls
    )
    ((job,),) = pages  # the email-to-apply row has no address and is dropped
    assert calls == [f"https://careers-api.clearcompany.com/v1/{GUID}?pageIndex=0&pageSize=100"]
    assert (job.title, job.company) == ("Data Analyst", "Northwind Labs")
    assert job.location == "Remote (Austin, TX, US)" and job.remote == "remote"
    assert job.url == "https://jobs.clearcompany.com/careers/jobs/1/apply"
    assert job.description == "Analyse data." and job.extra["id"] == "REQ-1"
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-10-01T12:00:00"


def test_a_repeated_page_ends_a_board_without_a_total(search_pages, load_fixture):
    rows = load_fixture("clearcompany/jobs.json")["results"]
    calls: list[str] = []
    pages = search_pages(
        ClearCompany(),
        lambda req: httpx.Response(200, json={"results": rows}),
        board=GUID,
        calls=calls,
    )
    assert len(pages) == 1 and len(calls) == 2


def test_url_patterns():
    embed = f"https://careers-content.clearcompany.com/js/v1/career-site.js?siteId={GUID}"
    assert detect(embed) == ("clearcompany", GUID)
    assert detect(f"https://careers-api.clearcompany.com/v1/{GUID}") == ("clearcompany", GUID)
    assert detect("https://www.clearcompany.com/") is None
