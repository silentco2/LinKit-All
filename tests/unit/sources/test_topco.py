import httpx
import pytest

from linkit_all.sources import registry
from linkit_all.sources.aggregators.topco import TopCo, flight, value_after
from linkit_all.sources.base import JobStub


def _stub(job_id: str) -> JobStub:
    return JobStub(source="topco", url=f"https://top.co/careers/{job_id}", title="t", company="c")


def test_the_flight_chunks_join_and_the_vacancies_decode(load_fixture):
    text = flight(load_fixture("topco/careers.html"))
    vacancies = value_after(text, '"vacancies":')
    assert [v["id"] for v in vacancies] == ["45804", "7", ""]  # a "]" inside a string is fine
    assert value_after(text, '"missing":') is None


def test_search_maps_vacancies(search_pages, load_fixture):
    (page,) = search_pages(
        TopCo(), lambda req: httpx.Response(200, text=load_fixture("topco/careers.html"))
    )
    cto, backend = page  # the vacancy without an id is dropped
    assert (cto.title, cto.company, cto.remote) == (
        "Chief Technology Officer / CTO", "Mira", "remote",
    )  # fmt: skip
    assert cto.url == "https://top.co/careers/45804" and backend.company == "Tribute"


def test_a_page_without_vacancies_is_an_error(search_pages):
    with pytest.raises(ValueError, match="no vacancies"):
        search_pages(TopCo(), lambda req: httpx.Response(200, text="<html>no flight</html>"))


def test_details_come_from_the_rsc_endpoint(fetch_details, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, text=load_fixture("topco/detail_45804.txt"))

    stub = fetch_details(TopCo(), handler, _stub("45804"))
    assert seen[0].headers["RSC"] == "1"
    assert stub.description == "Lead the team.\n\n5+ years.\n\nEquity."


def test_placeholders_and_failures_leave_the_description_empty(fetch_details, load_fixture):
    text = load_fixture("topco/detail_7.txt")
    assert (
        fetch_details(TopCo(), lambda r: httpx.Response(200, text=text), _stub("7")).description
        == ""
    )
    assert fetch_details(TopCo(), lambda r: httpx.Response(404), _stub("7")).description == ""


def test_it_is_an_opt_in_aggregator():
    assert registry()["topco"].kind == "aggregator"
