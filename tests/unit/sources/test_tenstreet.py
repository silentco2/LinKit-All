from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats import tenstreet
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http

COMPANY = "1492393"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    pages = {"83575": "job_83575", "83647": "job_83647", "83960": "job_gone"}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/share_app_index.php":
            return httpx.Response(200, text=load_fixture("tenstreet/listing.html"))
        if req.url.path == "/share_app_show_active_jobs.php":
            assert req.url.params["portal_user_id"] == "1"  # without it the page is empty
            return httpx.Response(
                200, text=load_fixture(f"tenstreet/{pages[req.url.params['active_job_id']]}.html")
            )
        return httpx.Response(404)

    return handler


def test_listing(load_fixture: Callable[[str], Any]) -> None:
    name, ids = tenstreet.listing(load_fixture("tenstreet/listing.html"), COMPANY)
    assert name == "Podium Logistics Express, LLC"
    assert ids == ["83575", "83647", "83960"]
    # another carrier's id is not a posting of this board
    assert tenstreet.listing(load_fixture("tenstreet/listing.html"), "774") == (name, [])


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(tenstreet.Tenstreet(), _serve(load_fixture), board=COMPANY)
    assert len(pages) == 1 and len(pages[0]) == 2  # 83960 answers an empty posting (closed)
    first, second = pages[0]
    assert first.title == "CDL A Regional Flatbed Owner Operator"
    assert first.company == "Podium Logistics Express, LLC" and first.location == "GA, US"
    assert first.url == tenstreet.posting_url(COMPANY, "83575") and first.apply_url == first.url
    assert first.extra == {"board": COMPANY, "id": "83575"} and first.ats == "tenstreet"
    assert "Requirements" in first.description and "<" not in first.description
    # 83647 has no requirements (null), so no empty section is added
    assert second.extra["id"] == "83647" and "Requirements" not in second.description
    assert second.description


def test_resume_skips_what_was_already_read(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert (
        search_pages(tenstreet.Tenstreet(), _serve(load_fixture), board=COMPANY, start_page=1) == []
    )


def test_rows_edge_cases() -> None:
    assert tenstreet.rows("<script>var active_job_array = null;</script>") == []
    assert tenstreet.rows("<html></html>") == []
    assert tenstreet.rows("<script>var active_job_array = [{broken</script>") == []
    stub = tenstreet.Tenstreet()._stub  # a page for another posting, or without a title
    assert stub([{"active_job_id": "1", "job_title": "T"}], "2", "u", "9", "C") is None
    assert stub([{"active_job_id": "1", "job_title": " "}], "1", "u", "9", "C") is None
    rows = [
        {"active_job_id": "1", "job_title": "Driver", "job_pay": " $1 ", "state": "tx"},
        {"active_job_id": "1", "location_type": "select_states", "value": "GA"},
        {"active_job_id": "1", "location_type": "zip_radius", "state": "TX", "value": "787"},
        {"active_job_id": "1", "state": "Texas"},  # not a state code
    ]
    done = stub(rows, "1", "u", "9", "C")
    assert done is not None and done.location == "TX, GA, US" and done.description == "Pay\n$1"


def test_unknown_company_and_bad_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(Unsupported):  # an unknown id answers 200 with an empty profile
        search_pages(
            tenstreet.Tenstreet(), lambda req: httpx.Response(200, text="<html></html>"), board="1"
        )
    with pytest.raises(Unsupported):
        search_pages(tenstreet.Tenstreet(), lambda req: httpx.Response(200), board="podium")


def test_url_patterns() -> None:
    url = f"https://pulse.tenstreet.com/share_app_show_active_jobs.php?active_job_id=83575&company_id={COMPANY}&portal_user_id=0"
    assert detect(url) == ("tenstreet", COMPANY)
    assert detect(f"https://pulse.tenstreet.com/share_app_index.php?company_id={COMPANY}") == (
        "tenstreet",
        COMPANY,
    )
    assert detect(f"tenstreet:{COMPANY}") == ("tenstreet", COMPANY)
