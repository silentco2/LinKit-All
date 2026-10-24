import copy

import httpx
import pytest

from linkit_all.sources.ats.adp import Adp, split_board
from linkit_all.sources.ats_detector import detect


def test_search_maps_the_list(search_pages, load_fixture):
    data = load_fixture("adp/list.json")
    calls: list[str] = []
    pages = search_pages(
        Adp(), lambda req: httpx.Response(200, json=data), board="thecid:9201_2", calls=calls
    )
    (stub,) = pages[0]
    assert stub.title == "Legal Counsel"
    assert stub.location == "Remote, EST, US"
    assert stub.remote == "remote"
    assert stub.url.endswith("cid=thecid&ccId=9201_2&jobId=9201_1&lang=en_US")
    assert stub.posted_at is not None and stub.posted_at.isoformat() == "2026-06-15T00:00:00"
    assert stub.ats == "adp" and stub.extra["id"] == "9201_1"
    assert "cid=thecid" in calls[0] and "%24top=50" in calls[0] and "%24skip=0" in calls[0]


def test_paging_and_resume(search_pages, load_fixture):
    item = load_fixture("adp/list.json")["jobRequisitions"][0]
    first = [{**copy.deepcopy(item), "itemID": f"a{i}"} for i in range(50)]
    second = [{**copy.deepcopy(item), "itemID": "b0"}]

    def handler(req: httpx.Request) -> httpx.Response:
        skip = int(req.url.params["$skip"])
        return httpx.Response(
            200, json={"meta": {"totalNumber": 51}, "jobRequisitions": [first, second][skip // 50]}
        )

    pages = search_pages(Adp(), handler, board="c/cc")
    assert [len(p) for p in pages] == [50, 1]
    calls: list[str] = []
    resumed = search_pages(Adp(), handler, board="c/cc", start_page=1, calls=calls)
    assert [s.extra["id"] for p in resumed for s in p] == ["b0"]
    assert "%24skip=50" in calls[0]


def test_fetch_details_reads_the_description(fetch_details, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("adp/detail.json"))

    base = Adp().stub({"itemID": "9201_1", "requisitionTitle": "Legal Counsel"}, "thecid", "9201_2")
    stub = fetch_details(Adp(), handler, base)
    assert "law" in stub.description and "<" not in stub.description
    assert "x()" not in stub.description
    assert seen[0].url.path.endswith("/job-requisitions/9201_1")
    assert seen[0].url.params["cid"] == "thecid" and seen[0].url.params["ccId"] == "9201_2"


def test_fetch_details_ignores_a_foreign_url(fetch_details):
    base = (
        Adp().stub({"itemID": "x"}, "c", "cc").model_copy(update={"url": "https://example.com/j"})
    )
    assert fetch_details(Adp(), lambda req: httpx.Response(500), base) is base


def test_board_forms_and_detection():
    assert split_board("c:cc_1") == ("c", "cc_1")
    assert split_board("c/cc_1") == ("c", "cc_1")
    with pytest.raises(ValueError):
        split_board("missingcolon")
    url = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=abc-1&ccId=9201289910657_2&lang=en_US"
    assert detect(url, [Adp()]) == ("adp", "abc-1/9201289910657_2")
    assert detect("adp:abc-1:99_2", [Adp()]) == ("adp", "abc-1:99_2")
