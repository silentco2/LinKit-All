from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.mtslink import MtsLink


def test_open_positions(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    items = load_fixture("mtslink/list.json")
    items[1]["state"] = "CLOSED"
    items.append({**items[0], "id": 9, "hidden": True})
    pages = search_pages(MtsLink(), lambda req: httpx.Response(200, json=items))
    assert len(pages) == 1 and len(pages[0]) == 1
    job = pages[0][0]
    assert job.title == "SDR (COMDI)" and job.company == "MTS Link"
    assert job.url == "https://mts-link.ru/vacancies/4326986/" and job.remote == "remote"
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-09-03T14:59:10"  # UTC
    assert search_pages(MtsLink(), lambda req: httpx.Response(200, json=items), start_page=1) == []


def test_details(fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]) -> None:
    stub = JobStub(
        source="mtslink", url="https://mts-link.ru/vacancies/4354305/", title="t", company="c"
    )
    got = fetch_details(
        MtsLink(), lambda req: httpx.Response(200, json=load_fixture("mtslink/detail.json")), stub
    )
    assert "COMDI" in got.description and "Мы ожидаем" in got.description
    assert fetch_details(MtsLink(), lambda req: httpx.Response(404), stub).description == ""
