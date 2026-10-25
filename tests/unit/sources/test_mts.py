# ruff: noqa: RUF001
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import mts
from linkit_all.sources.companies.mts import Mts

JAVA = "719596607967854689"


def api(
    load_fixture: Callable[[str], Any], seen: list[str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.host == "job.mts.ru":
            return httpx.Response(200, text=load_fixture("mts/site.html"))
        if seen is not None:
            seen.append(req.headers.get("x-api-key", ""))
        if req.url.path.endswith("/filtered/career"):
            offset = json.loads(req.content)["offset"]
            data = load_fixture("mts/list.json")
            vacancies = data["data"]["vacancies"]
            data["data"]["pageInfo"]["total"] = len(vacancies)
            data["data"]["vacancies"] = vacancies[offset : offset + mts.PAGE]
            return httpx.Response(200, json=data)
        if req.url.path == f"/v1/vacancy/{JAVA}":
            return httpx.Response(200, json=load_fixture("mts/detail.json"))
        return httpx.Response(404)

    return handle


def test_key_from_site_then_list(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    keys: list[str] = []
    pages = search_pages(Mts(), api(load_fixture, keys))
    assert keys == ["KEY-abc.def-123_xyz"]  # the key the site's page config carries
    java, bank = pages[0]
    assert java.title == "Ведущий разработчик Java" and java.company == "ПАО МТС-Банк"
    assert java.url == f"https://job.mts.ru/vacancy/{JAVA}" and java.apply_url == java.url
    assert java.location == "Москва" and java.remote == "onsite" and java.ats == "mts"
    assert java.extra["mts_id"] == JAVA and bank.location == "Рязань"


def test_pages_by_offset(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mts, "PAGE", 1)
    assert [len(p) for p in search_pages(Mts(), api(load_fixture))] == [1, 1]
    assert [p[0].location for p in search_pages(Mts(), api(load_fixture), start_page=1)] == [
        "Рязань"
    ]


def test_missing_key_fails(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="apiKey"):
        search_pages(Mts(), lambda req: httpx.Response(200, text="<html></html>"))


def test_details_send_the_key(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    keys: list[str] = []
    stub = JobStub(source="mts", url=f"https://job.mts.ru/vacancy/{JAVA}", title="t", company="c")
    got = fetch_details(Mts(), api(load_fixture, keys), stub)
    assert keys == ["KEY-abc.def-123_xyz"]
    assert "Spring Boot" in got.description and "МТС Банк развивает" in got.description
    gone = stub.model_copy(update={"url": "https://job.mts.ru/vacancy/1"})
    assert fetch_details(Mts(), api(load_fixture), gone).description == ""
