from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import oracle
from linkit_all.sources.ats.oracle import Oracle
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "fa-test.fa.ocs.oraclecloud.com/CX_1"


def make_handler(
    load_fixture: Callable[[str], Any], calls: list[str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if calls is not None:
            calls.append(url)
        assert req.url.host == "fa-test.fa.ocs.oraclecloud.com"
        if "recruitingCEJobRequisitionDetails" in url:
            ident = url.split("Id=%22")[1].split("%22")[0]
            if ident == "30610":  # one detail that cannot be read
                return httpx.Response(404)
            return httpx.Response(200, json=load_fixture(f"oracle/detail_{ident}.json"))
        assert "siteNumber=CX_1" in url
        return httpx.Response(200, json=load_fixture("oracle/list.json"))

    return handler


def test_list_then_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Oracle(), make_handler(load_fixture), board=BOARD)
    assert len(pages) == 1
    a, b = pages[0]  # 30610's detail failed, so it is left out
    assert (a.title, a.location) == ("Backend Engineer", "Berlin, Germany")
    assert (
        a.url
        == "https://fa-test.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/30607"
    )
    assert a.company == "Fa Test"  # named from the host: the API gives none
    assert a.remote == "onsite" and a.ats == "oracle"
    for want in ("Build the backend.", "Own services", "Go experience."):
        assert want in a.description
    assert a.posted_at is not None and a.posted_at.date().isoformat() == "2026-06-16"
    assert a.extra["board"] == BOARD and a.extra["id"] == "30607"
    # External* fields blank: the corporate and organisation blurbs carry the body
    assert b.title == "Summer Analyst" and b.remote == "hybrid"
    assert "About the program." in b.description and "About the division." in b.description


def test_offset_sits_in_the_finder(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oracle ignores a top-level offset; paging goes in the finder clause, and a resumed run
    starts at its page."""
    monkeypatch.setattr(oracle, "PAGE", 2)
    calls: list[str] = []
    handler = make_handler(load_fixture, calls)
    pages = search_pages(Oracle(), handler, board=BOARD, calls=calls)
    assert len(pages) == 1  # the list page held 3 > 2 rows and the total is reached after it
    lists = [c for c in calls if "findReqs" in c]
    assert "limit=2,offset=0," in lists[0]
    calls.clear()
    search_pages(Oracle(), handler, board=BOARD, start_page=1, calls=calls)
    assert "limit=2,offset=2," in next(c for c in calls if "findReqs" in c)


def test_bad_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="host/site"):
        search_pages(Oracle(), lambda r: httpx.Response(200), board="just-a-host")


def test_url_patterns() -> None:
    url = "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/requisitions"
    assert detect(url) == ("oracle", "eeho.fa.us2.oraclecloud.com/CX_1")
    assert detect(f"oracle:{BOARD}") == ("oracle", BOARD)
