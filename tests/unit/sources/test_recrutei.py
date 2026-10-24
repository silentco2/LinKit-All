import json

import httpx
import pytest

from linkit_all.sources.ats.recrutei import Recrutei, places, posted
from linkit_all.sources.ats_detector import detect

API = "/api/v2/vacancies/per-departments/digisystem"


def test_places_and_date():
    assert places(["Brasilia", "DF", "Brasil"]) == "Brasilia, DF, Brasil"
    assert places("Não informado") == "" and places(None) == ""
    assert places("Lisboa") == "Lisboa"
    assert posted("14/07/2025 14:37:27").isoformat() == "2025-07-14T14:37:27"  # type: ignore[union-attr]
    assert posted("undefined") is None


def test_search_lists_every_department(search_pages, load_fixture):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("recrutei/listing.json"))

    pages = search_pages(Recrutei(), handler, board="digisystem")
    a, b, c = pages[0]
    assert bodies == [{"search": ""}]
    assert (a.title, a.company, a.location) == (
        "Analista de Suporte N2 Jr",
        "Digisystem",
        "Brasilia, DF, Brasil",
    )
    assert a.url == "https://jobs.recrutei.com.br/digisystem/vacancy/108736-analista"
    assert a.extra == {"board": "digisystem", "id": "108736", "employment": "full_time"}
    assert b.extra["employment"] == "contract"  # Pessoa Juridica
    assert (c.location, c.remote) == ("", "remote")  # the "not stated" placeholder is no location
    assert a.ats == "recrutei"


def test_a_total_that_disagrees_fails_the_board(search_pages, load_fixture):
    data = load_fixture("recrutei/listing.json")
    data["data"]["total"] = 9
    with pytest.raises(ValueError, match="declared total 9"):
        search_pages(Recrutei(), lambda req: httpx.Response(200, json=data), board="digisystem")


def test_fetch_details_reads_description_and_date(search_pages, fetch_details, load_fixture):
    stub = search_pages(
        Recrutei(),
        lambda req: httpx.Response(200, json=load_fixture("recrutei/listing.json")),
        board="digisystem",
    )[0][0]
    page = load_fixture("recrutei/vacancy.html")
    full = fetch_details(Recrutei(), lambda req: httpx.Response(200, text=page), stub)
    assert full.description == "Suporte ao cliente."
    assert full.posted_at is not None and full.posted_at.isoformat() == "2025-07-14T14:37:27"
    bare = fetch_details(Recrutei(), lambda req: httpx.Response(200, text="<html/>"), stub)
    assert bare == stub


def test_url_patterns():
    assert detect("https://jobs.recrutei.com.br/digisystem/vacancy/108736-analista") == (
        "recrutei",
        "digisystem",
    )
    assert detect("recrutei:digisystem") == ("recrutei", "digisystem")
