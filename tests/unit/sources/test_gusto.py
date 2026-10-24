from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.gusto import Gusto
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "grupo-ei-el-paso-7feb4b68-5288-41cc-b169-f56b3ec26120"
FORKLIFT = "grupo-ei-el-paso-forklift-operator-dad51777-4520-4500-a8f8-228b55fb90bb"


def _board(load_fixture: Callable[[str], Any], calls: list[str]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(str(req.url))
        return httpx.Response(
            200, text=load_fixture(f"gusto/board_page{req.url.params['page']}.html")
        )

    return handler


def test_walks_pages_until_an_empty_one(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Gusto(), _board(load_fixture, calls), board=BOARD)
    assert calls == [f"{'https://jobs.gusto.com/boards/' + BOARD}?page={n}" for n in (1, 2)]
    assert len(pages) == 1 and len(pages[0]) == 4
    forklift, clerk, warehouse, lead = pages[0]
    assert forklift.title == "Forklift Operator" and forklift.company == "Grupo Ei El Paso"
    assert forklift.url == f"https://jobs.gusto.com/postings/{FORKLIFT}"
    assert forklift.location == "El Paso, TX"
    assert (forklift.salary_min, forklift.salary_max) == (12.0, 16.0)
    assert (forklift.salary_currency, forklift.salary_interval) == ("USD", "hour")
    assert forklift.extra == {
        "board": BOARD,
        "id": "dad51777-4520-4500-a8f8-228b55fb90bb",
        "employment": "Full time",
    }
    assert forklift.ats == "gusto" and forklift.description == ""
    assert clerk.title == "Revisador de Mercancias" and clerk.salary_max == 14.0
    assert warehouse.title == "Warehouse Clerk" and warehouse.salary_min == 14.0
    assert lead.title == "Warehouse Team Lead" and lead.extra["id"].startswith("f6a50f1f")


def test_resume_skips_earlier_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Gusto(), _board(load_fixture, calls), board=BOARD, start_page=1)
    assert pages == [] and len(calls) == 1 and calls[0].endswith("page=2")


def test_details_join_the_pitch_and_description_but_not_the_company_blurb(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="gusto", url=f"https://jobs.gusto.com/postings/{FORKLIFT}", title="F", company="G"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("gusto/posting_forklift.html"))

    out = fetch_details(Gusto(), handler, stub)
    assert out.description.startswith("Operates forklift to move merchandise")
    assert "A Forklift Operator, or Material Handler, is a certified warehouse" in out.description
    assert "4PL company" not in out.description  # the "About <employer>" section
    assert "<p>" not in out.description


def test_pay_line_without_a_salary_or_with_weekly_pay() -> None:
    from selectolax.lexbor import LexborHTMLParser

    def card(line: str) -> JobStub | None:
        html = (
            f'<a href="/postings/x-job-{BOARD[-36:]}"><h3>Job</h3>'
            f"<p>Austin, TX</p><p>{line}</p></a>"
        )
        node = LexborHTMLParser(html).css_first("a")
        assert node is not None
        return Gusto.stub(node, "b", "B")

    none = card("Part time")
    assert none is not None and none.salary_min is None and none.extra["employment"] == "Part time"
    weekly = card("$900 - $1,000 per week &middot; Contractor".replace("&middot;", "·"))
    assert weekly is not None and weekly.salary_min is None
    assert weekly.extra["employment"] == "Contractor"
    monthly = card("$4,000 - $5,500.50 per month · Full time")
    assert monthly is not None and (monthly.salary_min, monthly.salary_max) == (4000.0, 5500.5)


def test_url_patterns() -> None:
    assert detect(f"https://jobs.gusto.com/boards/{BOARD}") == ("gusto", BOARD)
