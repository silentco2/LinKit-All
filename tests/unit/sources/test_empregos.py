import json

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.empregos import Empregos


def test_search_posts_the_keyword_and_maps_postings(search_pages, load_fixture):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("empregos/search.json"))

    (page,) = search_pages(Empregos(), handler, query="analista")
    assert bodies == [
        {"keyword": "analista", "filters": [], "page": 0, "size": 100, "order": 0, "distance": 100}
    ]
    recruiter, stock = page  # the "Empresa confidencial" posting is skipped
    assert recruiter.title == "Tech Recruiter – Foco em Tecnologia da Informação"  # noqa: RUF001
    assert (recruiter.company, recruiter.location) == ("Angellira", "Chapecó, SC")
    assert recruiter.url == "https://www.empregos.com.br/vaga/11946733"
    assert recruiter.remote == "onsite" and recruiter.extra == {"id": 11946733}
    assert recruiter.description.startswith("Responsabilidades Técnicas")
    # 2026-10-22 10:05 in Brasilia time (UTC-3) is 13:05 UTC
    assert recruiter.posted_at is not None
    assert (recruiter.posted_at.day, recruiter.posted_at.hour) == (22, 13)
    assert "&nbsp;" not in stock.description and "\xa0" not in stock.description  # plain-text body
    assert stock.description.startswith("Estamos em busca de um Analista de Estoque")


def test_sections_are_appended_to_the_description(search_pages, load_fixture):
    data = load_fixture("empregos/search.json")
    data["jobPostingCollection"][0].update(
        requiredQualification="<p>Python</p>", academicFormation="Superior", workTime="Integral"
    )
    (page,) = search_pages(Empregos(), lambda r: httpx.Response(200, json=data), query="x")
    desc = page[0].description
    assert "Requisitos:\nPython" in desc and "Formação:\nSuperior" in desc
    assert desc.endswith("Horário:\nIntegral")


def test_paging_uses_zero_based_pages_until_the_total(search_pages, load_fixture):
    pages_asked: list[int] = []
    row = load_fixture("empregos/search.json")["jobPostingCollection"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        page = json.loads(req.content)["page"]
        pages_asked.append(page)
        rows = [{**row, "referenceId": page * 1000 + i + 1} for i in range(100)]
        return httpx.Response(200, json={"total": 250, "jobPostingCollection": rows})

    pages = search_pages(Empregos(), handler, query="x", limit=300)
    assert pages_asked == [0, 1, 2] and [len(p) for p in pages] == [100, 100, 100]
    pages_asked.clear()
    search_pages(Empregos(), handler, query="x", limit=300, start_page=2)
    assert pages_asked == [2]


def test_tasks_ignore_locations_and_it_is_an_opt_in_aggregator():
    cfg = SearchConfig.model_validate({"search": {"queries": ["a", "b"], "locations": ["x", "y"]}})
    assert [t.query for t in Empregos().tasks(cfg)] == ["a", "b"]
    assert registry()["empregos"].kind == "aggregator"
