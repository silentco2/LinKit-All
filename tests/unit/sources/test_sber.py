# ruff: noqa: RUF001
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import sber
from linkit_all.sources.companies.sber import Sber


def test_publications(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("sber/list.json")
    data["data"]["total"] = 2
    pages = search_pages(Sber(), lambda req: httpx.Response(200, json=data))
    assert len(pages) == 1 and len(pages[0]) == 2
    job = pages[0][0]
    assert job.title == "Старший клиентский менеджер" and job.company == "ПАО Сбербанк"
    assert job.url == "https://rabota.sber.ru/search/4482579" and job.location == "г Курчатов"
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-10-24T10:09:03"
    assert (
        job.description.startswith("Ищешь работу") and "консультировать клиентов" in job.description
    )
    assert job.extra["sber_id"] == "8ad3f845-8f66-4264-aece-2e52c47468ec"


def test_skip_take_paging(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sber, "PAGE", 1)
    vacancies = load_fixture("sber/list.json")["data"]["vacancies"]

    def handler(req: httpx.Request) -> httpx.Response:
        skip = int(req.url.params["skip"])
        return httpx.Response(
            200, json={"data": {"vacancies": vacancies[skip : skip + 1], "total": 2}}
        )

    assert [p[0].title for p in search_pages(Sber(), handler)] == [
        "Старший клиентский менеджер",
        "Стажер LLM",
    ]
    assert [p[0].title for p in search_pages(Sber(), handler, start_page=1)] == ["Стажер LLM"]
