from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.vk import PAGE, VK


def test_search_pages_with_offset_and_resumes(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("vk/list_p1.json")  # count 3, three rows (one untitled)
    calls: list[str] = []
    pages = search_pages(VK(), lambda req: httpx.Response(200, json=data), calls=calls)
    assert calls == [f"https://team.vk.company/career/api/v2/vacancies/?limit={PAGE}&offset=0"]
    backend, sre = pages[0]  # the row without a title is left out
    assert backend.title == "Backend Engineer" and backend.company == "VK"
    assert backend.url == "https://team.vk.company/vacancy/100/" and backend.location == "Москва"
    assert backend.remote is None and sre.remote == "remote" and backend.ats == "vk"
    assert backend.extra["id"] == "100"
    calls.clear()
    search_pages(VK(), lambda req: httpx.Response(200, json=data), start_page=1, calls=calls)
    assert calls[0].endswith(f"offset={PAGE}")


def test_fetch_details_reads_the_description_microdata(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    html = load_fixture("vk/vacancy_100.html")
    source = VK()
    source.detail_pause = 0
    stub = JobStub(source="vk", url="https://team.vk.company/vacancy/100/", title="t", company="VK")
    out = fetch_details(source, lambda req: httpx.Response(200, text=html), stub)
    assert "Build services." in out.description and "Code" in out.description
    assert "alert" not in out.description
    # A rate-limit challenge page has no microdata: the stub keeps no description.
    challenged = fetch_details(
        source, lambda req: httpx.Response(200, text="<html>429</html>"), stub
    )
    assert challenged.description == ""


def test_pause_default_and_task() -> None:
    assert VK.detail_pause == 5.0
    assert VK().tasks(SearchConfig())[0].board == "team.vk.company"
