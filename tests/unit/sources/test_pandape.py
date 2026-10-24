import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import pandape
from linkit_all.sources.ats.pandape import Card, Pandape, parse_cards, parse_vacancy
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

SITE = "braspress.pandape.infojobs.com.br"


def make_handler(
    load_fixture: Callable[[str], Any], pages: int = 3, calls: list[str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if calls is not None:
            calls.append(f"{req.method} {req.url.path}")
        if req.url.path == "/ListVacancies":
            assert req.method == "POST" and req.headers["X-Requested-With"] == "XMLHttpRequest"
            form = dict(p.split("=") for p in req.content.decode().split("&"))
            n = int(form["PageNumber"])
            if n > pages:
                return httpx.Response(404)
            return httpx.Response(200, json=load_fixture(f"pandape/braspress_page{n}.json"))
        if req.url.path == "/Detail/3861560":
            return httpx.Response(200, text=load_fixture("pandape/braspress_detail.html"))
        return httpx.Response(404)  # the other vacancies' pages are not in the fixture

    return handler


def test_cards_read_title_and_facts(load_fixture: Callable[[str], Any]) -> None:
    cards = parse_cards(load_fixture("pandape/abaco_page1.json")["view"])
    assert len(cards) == 9
    card = cards[2]
    assert (card.id, card.title) == ("3518777", "Consultor(a) SAP MM Sênior")
    assert (card.location, card.work_mode) == ("Todo Brasil", "Home Office")
    assert card.contract == "Prestador de Serviços (PJ)"
    assert cards[3].work_mode == "Híbrido"


def test_walks_every_page_and_reads_the_vacancy(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Pandape(), make_handler(load_fixture, calls=calls), board="braspress")
    assert [c for c in calls if "ListVacancies" in c] == ["POST /ListVacancies"] * 3
    (job,) = pages[0]  # only one of the five vacancies has a page in the fixture
    assert job.title == "Ajudante de Manutenção Mecânica" and job.company == "Braspress"
    assert job.url == f"https://{SITE}/Detail/3861560" and job.ats == "pandape"
    assert job.location == "Guarulhos, SP" and job.remote == "onsite"
    assert "🚍 Vale Transporte" in job.description and "Requisitos" in job.description
    # 15:59:35 Brasília time is 18:59:35 UTC
    assert job.posted_at is not None and job.posted_at.isoformat().startswith("2026-10-23T18:59:35")
    assert job.extra["board"] == "braspress" and job.extra["id"] == "3861560"


def test_home_office_card_and_salary(load_fixture: Callable[[str], Any]) -> None:
    cards = parse_cards(load_fixture("pandape/abaco_page1.json")["view"])
    url = "https://abacoconsulting.pandape.infojobs.com.br/Detail/3518777"
    job = parse_vacancy(
        load_fixture("pandape/abaco_detail_homeoffice.html"), cards[2], url, "abaco"
    )
    assert job is not None
    assert job.remote == "remote" and job.location and job.extra["contract"].startswith("Prestador")
    card = Card(
        "3721298", "Project Buyer (Comprador de Projeto)", "", "Presencial", "Efetivo - CLT"
    )
    paid = parse_vacancy(
        load_fixture("pandape/randstad_detail_salary.html"),
        card,
        "https://randstad-brasil.pandape.infojobs.com.br/Detail/3721298",
        "randstad-brasil",
    )
    assert paid is not None and paid.location == "Campina Grande do Sul, PR"
    assert (paid.salary_min, paid.salary_max) == (5000, 5500)
    assert paid.salary_currency == "BRL" and paid.salary_interval == "month"


def test_short_walk_and_unknown_tenant_fail(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def stated_six(req: httpx.Request) -> httpx.Response:
        resp = make_handler(load_fixture)(req)
        if req.url.path == "/ListVacancies" and not resp.is_error:
            return httpx.Response(200, json=json.loads(resp.text) | {"subtotal": 6})
        return resp

    with pytest.raises(ValueError, match="site states 6"):
        search_pages(Pandape(), stated_six, board="braspress")
    with pytest.raises(ValueError, match="does not exist"):
        search_pages(Pandape(), make_handler(load_fixture, pages=0), board="nosuchtenant")
    with pytest.raises(ValueError, match="tenant label"):
        search_pages(Pandape(), lambda r: httpx.Response(200), board="a.b")


def test_a_later_page_failing_fails_the_crawl(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(Pandape(), make_handler(load_fixture, pages=1), board="braspress")


def test_no_vacancy_page_readable_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/Detail/"):
            return httpx.Response(404)
        return make_handler(load_fixture)(req)

    with pytest.raises(ValueError, match="read none"):
        search_pages(Pandape(), handler, board="braspress")


def test_resume_and_patterns(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pandape, "CHUNK", 2)
    pages = search_pages(Pandape(), make_handler(load_fixture), board="braspress", start_page=1)
    assert pages == [[], []]  # the card list is re-walked; pages 1 and 2 hold no readable vacancy
    assert detect(f"https://{SITE}/Detail/3861560") == ("pandape", "braspress")
    assert detect("pandape:randstad-brasil") == ("pandape", "randstad-brasil")
