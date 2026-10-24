from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.hrmanager import HrManager, _date
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search_reads_the_whole_customer_in_one_call(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("hrmanager/energinet.json"))

    pages = search_pages(HrManager(), handler, board="energinet")
    assert len(seen) == 1
    assert seen[0].url.path == "/jobportal.svc/energinet/positionlist/json/"
    assert seen[0].url.params["incads"] == "1" and seen[0].url.params["take"] == "2000"
    assert len(pages) == 1 and len(pages[0]) == 3  # the open application is dropped
    ceo = pages[0][0]
    assert ceo.title == "Administrerende direktør til Energinet" and ceo.company == "Energinet"
    assert ceo.url == (
        "https://candidate.hr-manager.net/ApplicationInit.aspx"
        "?cid=316&ProjectId=188952&DepartmentId=9728&MediaId=5"
    )
    assert ceo.location == "Fredericia / Ballerup"
    assert ceo.description and "<p>" not in ceo.description
    assert ceo.posted_at is not None and ceo.posted_at.year == 2026
    assert ceo.extra == {"board": "energinet", "id": "188952"} and ceo.ats == "hrmanager"
    assert pages[0][1].location == "Fredericia"


def test_resume_past_the_single_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = lambda req: httpx.Response(200, json=load_fixture("hrmanager/energinet.json"))  # noqa: E731
    assert search_pages(HrManager(), handler, board="energinet", start_page=1) == []


def test_an_unknown_customer_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = lambda req: httpx.Response(200, json=load_fixture("hrmanager/unknown_customer.json"))  # noqa: E731
    with pytest.raises(ValueError, match="status 1"):
        search_pages(HrManager(), handler, board="nobody")


def test_a_listing_of_another_customer_or_a_bad_alias_is_refused(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = lambda req: httpx.Response(200, json=load_fixture("hrmanager/energinet.json"))  # noqa: E731
    with pytest.raises(ValueError, match="names customer"):
        search_pages(HrManager(), handler, board="rema1000")
    with pytest.raises(ValueError, match="not a customer alias"):
        search_pages(HrManager(), handler, board="a/b")


def test_dates_and_url_patterns() -> None:
    assert _date("/Date(1791377991000+0200)/") is not None
    assert _date("/Date(-62135596800000)/") is None  # .NET DateTime.MinValue: never set
    assert _date("2026-01-01") is None
    assert detect("https://api.hr-manager.net/jobportal.svc/energinet/positionlist/json/") == (
        "hrmanager",
        "energinet",
    )
