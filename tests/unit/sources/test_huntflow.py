from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.huntflow import Huntflow, find_vacancy, unflatten
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/_payload.json":
            return httpx.Response(200, json=load_fixture("huntflow/list.json"))
        if path == "/vacancy/senior-backend-developer/_payload.json":
            return httpx.Response(200, json=load_fixture("huntflow/detail.json"))
        return httpx.Response(404)

    return handler


def test_unflatten_resolves_references_and_wrappers() -> None:
    raw = [{"data": 1}, {"vacancies": 2}, {"items": 3}, [4], {"id": 5, "city": 6}, 26610, None]
    assert unflatten(raw) == {"data": {"vacancies": {"items": [{"id": 26610, "city": None}]}}}
    assert unflatten([{"data": 1}, ["ShallowReactive", 2], "ok"]) == {"data": "ok"}
    assert unflatten([{"self": 0}]) == {"self": None}  # a cycle does not recurse forever
    assert unflatten([]) is None


def test_find_vacancy_walks_the_route_state() -> None:
    node = {"a": [{"x": 1}, {"b": {"position": "Dev", "body": "<p>x</p>"}}]}
    assert find_vacancy(node) == {"position": "Dev", "body": "<p>x</p>"}
    assert find_vacancy({"a": 1}) is None


def test_search_skips_archived_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Huntflow(), _serve(load_fixture), board="acme")
    assert len(pages) == 1 and len(pages[0]) == 1  # "old-role" is archived
    job = pages[0][0]
    assert job.title == "Senior Backend Developer" and job.location == "Kyiv"
    assert job.url == "https://acme.huntflow.io/vacancy/senior-backend-developer"
    assert job.company == "Acme" and job.ats == "huntflow" and job.description == ""
    assert job.extra == {"board": "acme", "id": "26610", "slug": "senior-backend-developer"}
    assert search_pages(Huntflow(), _serve(load_fixture), board="acme", start_page=1) == []


def test_fetch_details_joins_the_sections_and_money(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="huntflow",
        url="https://acme.huntflow.io/vacancy/senior-backend-developer",
        title="Senior Backend Developer",
        company="Acme",
    )
    done = fetch_details(Huntflow(), _serve(load_fixture), stub)
    assert done.description.startswith("$5000-6000")
    assert "Build APIs." in done.description and "Remote friendly." in done.description
    assert done.location == "Kyiv"
    gone = stub.model_copy(update={"url": "https://acme.huntflow.io/vacancy/missing"})
    with pytest.raises(httpx.HTTPStatusError):
        fetch_details(Huntflow(), _serve(load_fixture), gone)


def test_url_patterns() -> None:
    assert detect("https://acme.huntflow.io/vacancy/senior-backend-developer") == (
        "huntflow",
        "acme",
    )
    assert detect("huntflow:acme") == ("huntflow", "acme")
