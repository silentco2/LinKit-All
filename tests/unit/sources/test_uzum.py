from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.uzum import SITEMAP, Uzum, body_html, parse_vacancy

BASE = "https://people.uzum.com/career/ru/vacancies/"


def test_search_reads_russian_vacancy_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages_by_path = {
        "/sitemap.xml": load_fixture("uzum/uzum_sitemap.xml"),
        "/career/ru/vacancies/3384": load_fixture("uzum/uzum_vacancy_3384.html"),
        "/career/ru/vacancies/3770": load_fixture("uzum/uzum_vacancy_3770.html"),
    }
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        text = pages_by_path.get(req.url.path)
        return httpx.Response(200, text=text) if text else httpx.Response(404)

    pages = search_pages(Uzum(), handler, calls=calls)
    assert SITEMAP in calls
    assert not any("/career/uz/" in c for c in calls)  # the Uzbek copies are never read
    assert len(pages) == 1
    by_id = {s.extra["id"]: s for s in pages[0]}
    assert set(by_id) == {"3384", "3770"}  # 3692 and 3700 answer 404: withdrawn
    analyst = by_id["3384"]
    assert analyst.title == "Senior System Analyst \\ Cистемный Аналитик"  # noqa: RUF001
    assert analyst.company == "Uzum Bank" and analyst.location == "Ташкент, Узбекистан"
    assert analyst.url == f"{BASE}3384" and analyst.remote == "remote" and analyst.ats == "uzum"
    assert analyst.posted_at is not None and analyst.posted_at.isoformat() == "2026-06-12T00:00:00"
    assert (
        analyst.description.startswith("Чем предстоит заниматься:")
        and "<" not in analyst.description
    )
    assert by_id["3770"].remote == "onsite"


def test_withdrawn_and_foreign_pages_are_not_parsed(load_fixture: Callable[[str], Any]) -> None:
    page = load_fixture("uzum/uzum_vacancy_3384.html")
    assert parse_vacancy(page, f"{BASE}3384") is not None
    assert parse_vacancy(page, f"{BASE}9999") is None  # the page is for another id
    assert parse_vacancy(page, "https://people.uzum.com/career/uz/vacancies/3384") is None
    assert (
        parse_vacancy(
            page.replace('\\"status\\":\\"Published\\"', '\\"status\\":\\"Draft\\"'), f"{BASE}3384"
        )
        is None
    )
    assert parse_vacancy("<html>no flight</html>", f"{BASE}3384") is None


def test_body_document_and_task() -> None:
    doc = '{"components":[{"type":"text","value":{"body":"<p>a</p>"}},{"type":"x","value":{}}]}'
    assert body_html(doc) == "<p>a</p>"
    assert body_html("<p>plain</p>") == "<p>plain</p>" and body_html("{broken") == "{broken"
    assert Uzum().tasks(SearchConfig())[0].board == "people.uzum.com"
