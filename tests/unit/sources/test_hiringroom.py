from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from linkit_all.sources.ats.hiringroom import HiringRoom, cards
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

VACANCY = "69b1d48a1121b4005a5cce59"


def _pager(load_fixture: Callable[[str], Any], tenant: str, forms: list[dict[str, str]]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.method == "POST"
        page = req.url.path.rsplit("/", 1)[-1]
        forms.append({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(200, json=load_fixture(f"hiringroom/{tenant}_page{page}.json"))

    return handler


def test_single_page_card_facts(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    forms: list[dict[str, str]] = []
    pages = search_pages(HiringRoom(), _pager(load_fixture, "emblue", forms), board="emblue")
    assert forms == [{"selectedPage": "1", "typePortal": "external"}]
    assert len(pages) == 1 and len(pages[0]) == 1
    job = pages[0][0]
    assert job.title == "Account Executive (Hunter) - España"
    assert job.url == f"https://emblue.hiringroom.com/jobs/get_vacancy/{VACANCY}"
    assert job.company == "Emblue" and job.location == "Madrid, España"
    assert job.remote == "hybrid"  # "Híbrido"
    assert job.extra["id"] == VACANCY and job.extra["level"] == "Senior"
    assert job.extra["schedule"] == "Full-time" and job.ats == "hiringroom"


def test_pages_until_the_stated_total(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    forms: list[dict[str, str]] = []
    pages = search_pages(HiringRoom(), _pager(load_fixture, "stefanini", forms), board="stefanini")
    assert [len(p) for p in pages] == [2, 1]  # 3 vacancies across two pages
    assert [f["selectedPage"] for f in forms] == ["1", "2"]
    forms.clear()
    pages = search_pages(
        HiringRoom(), _pager(load_fixture, "stefanini", forms), board="stefanini", start_page=1
    )
    assert [len(p) for p in pages] == [1]  # resumed: page 1 is walked but not yielded again


def test_a_page_that_adds_nothing_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    page1 = load_fixture("hiringroom/stefanini_page1.json")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json=page1)  # page 2 repeats page 1: total 3 is never reached

    with pytest.raises(ValueError, match="added no vacancy"):
        search_pages(HiringRoom(), handler, board="stefanini")


def test_a_bad_tenant_label_is_refused(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="not a tenant label"):
        search_pages(HiringRoom(), lambda req: httpx.Response(200), board="a/b")


def test_details_join_headed_sections_and_name_the_employer(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = HiringRoom.stub({"id": VACANCY, "title": "Account Executive"}, "emblue")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.url.path == f"/jobs/get_vacancy/{VACANCY}"
        return httpx.Response(200, text=load_fixture("hiringroom/emblue_vacancy.html"))

    out = fetch_details(HiringRoom(), handler, stub)
    assert out.company == "emBlue"  # from "Nuevas oportunidades de empleo: ... en emBlue"
    assert out.description.startswith("Descripción del puesto\nBuscamos Ejecutivos de Cuentas")
    assert "\n\nRequisitos\n" in out.description
    assert "Gestión Comercial y Ventas:" in out.description  # entities decoded
    assert "<p" not in out.description


def test_a_catch_all_vacancy_has_no_body(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = HiringRoom.stub({"id": VACANCY, "title": "Base general"}, "stefanini")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("hiringroom/stefanini_catchall_vacancy.html"))

    out = fetch_details(HiringRoom(), handler, stub)
    assert out.description == "" and out.company == "STEFANINI PERU S.A"


def test_cards_and_url_patterns(load_fixture: Callable[[str], Any]) -> None:
    html = load_fixture("hiringroom/emblue_page1.json")["data"]["htmlContent"]
    assert [(c["id"], c["modality"]) for c in cards(html)] == [(VACANCY, "Híbrido")]
    assert cards("<a href='/jobs/other'><h4 class='name__vacancy'>x</h4></a>") == []
    assert detect(f"https://emblue.hiringroom.com/jobs/get_vacancy/{VACANCY}") == (
        "hiringroom",
        "emblue",
    )
    assert detect("https://www.hiringroom.com/") is None
