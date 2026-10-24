from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.inhire import Inhire, slugify
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

ONE = "11111111-2222-3333-4444-555555555555"


def _serve(
    load_fixture: Callable[[str], Any], seen: list[httpx.Request] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if req.url.path == "/job-posts/public/pages":
            return httpx.Response(200, json=load_fixture("inhire/list.json"))
        if req.url.path == f"/job-posts/public/pages/{ONE}":
            return httpx.Response(200, json=load_fixture("inhire/detail.json"))
        return httpx.Response(404)

    return handler


def test_slugify() -> None:
    assert slugify("Engenheiro Sênior de Backend") == "engenheiro-senior-de-backend"
    assert slugify("???") == "vaga"  # the SPA renders blank without a slug segment


def test_search_sends_the_tenant_header(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []
    pages = search_pages(Inhire(), _serve(load_fixture, seen), board="contaazul")
    assert seen[0].headers["X-Tenant"] == "contaazul"
    first, second = pages[0]
    assert first.title == "Engenheiro Sênior de Backend"
    assert first.url == f"https://contaazul.inhire.app/vagas/{ONE}/engenheiro-senior-de-backend"
    assert first.location == "São Paulo, BR" and first.remote == "remote"
    assert first.company == "Contaazul" and first.ats == "inhire"
    assert first.extra == {"board": "contaazul", "id": ONE}
    assert second.remote == "onsite"
    assert search_pages(Inhire(), _serve(load_fixture), board="contaazul", start_page=1) == []


def test_fetch_details_unescapes_the_body(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []
    stub = JobStub(
        source="inhire",
        url=f"https://contaazul.inhire.app/vagas/{ONE}/engenheiro",
        title="Engenheiro",
        company="Contaazul",
    )
    done = fetch_details(Inhire(), _serve(load_fixture, seen), stub)
    assert done.description == "Build & ship."
    assert done.posted_at is not None and done.posted_at.day == 15  # publishedAt over createdAt
    assert seen[0].headers["X-Tenant"] == "contaazul"
    kept = stub.model_copy(update={"description": "kept"})
    assert fetch_details(Inhire(), _serve(load_fixture), kept).description == "kept"
    with pytest.raises(httpx.HTTPStatusError):
        fetch_details(
            Inhire(),
            _serve(load_fixture),
            stub.model_copy(update={"url": "https://contaazul.inhire.app/vagas/zzz/x"}),
        )


def test_url_patterns() -> None:
    assert detect(f"https://contaazul.inhire.app/vagas/{ONE}/x") == ("inhire", "contaazul")
    assert detect("inhire:acme") == ("inhire", "acme")
    assert detect("https://api.inhire.app/job-posts/public/pages") is None  # the API host
