import httpx
import pytest

from linkit_all.sources.ats.bullhorn import Bullhorn, split_board
from linkit_all.sources.ats_detector import detect


def test_search_maps_job_orders(search_pages, load_fixture):
    data = load_fixture("bullhorn/page.json")
    calls: list[str] = []
    pages = search_pages(
        Bullhorn(), lambda req: httpx.Response(200, json=data), board="91:abc123def", calls=calls
    )
    a, b = pages[0]
    assert a.title == "Senior Go Engineer"
    assert a.url == (
        "https://public-rest91.bullhornstaffing.com/rest-services/abc123def/entity/JobOrder/4231"
    )
    assert a.location == "Austin, TX"
    assert "Build backends." in a.description and "alert" not in a.description
    assert a.posted_at is not None and a.posted_at.isoformat() == "2025-06-22T18:43:19"
    assert a.extra["employment"] == "Contract To Hire" and a.ats == "bullhorn"
    assert b.location == "Canada" and b.posted_at is None
    assert len(calls) == 1  # total reached: no second page
    assert "isOpen" in calls[0] and "count=500" in calls[0] and "start=0" in calls[0]


def test_paging_and_resume(search_pages, load_fixture):
    row = load_fixture("bullhorn/page.json")["data"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        start = int(req.url.params["start"])
        count = 500 if start == 0 else 3
        data = [{**row, "id": start + i + 1} for i in range(count)]
        return httpx.Response(200, json={"total": 503, "data": data})

    assert [len(p) for p in search_pages(Bullhorn(), handler, board="1/tok")] == [500, 3]
    calls: list[str] = []
    resumed = search_pages(Bullhorn(), handler, board="1/tok", start_page=1, calls=calls)
    assert [len(p) for p in resumed] == [3] and "start=500" in calls[0]


def test_board_forms_and_detection():
    assert split_board("91:abc") == ("91", "abc")
    assert split_board("91/abc") == ("91", "abc")
    with pytest.raises(ValueError):
        split_board("abc")
    url = "https://public-rest91.bullhornstaffing.com/rest-services/abc123/search/JobOrder"
    assert detect(url, [Bullhorn()]) == ("bullhorn", "91/abc123")
