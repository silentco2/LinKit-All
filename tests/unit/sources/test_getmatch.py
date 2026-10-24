import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.getmatch import GetMatch
from linkit_all.sources.base import JobStub


def test_search_maps_offers_and_the_work_mode(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("getmatch/offers.json"))

    (page,) = search_pages(GetMatch(), handler)
    assert dict(seen[0].url.params) == {"offset": "0", "limit": "100"}
    golang, remote = page
    assert (golang.title, golang.company, golang.location) == (
        "Senior Golang Developer", "HR Prime", "Москва",
    )  # fmt: skip
    assert golang.url == "https://getmatch.ru/vacancies/34895-senior-golang"
    assert golang.remote == "onsite" and golang.description == ""
    assert golang.posted_at is not None and golang.posted_at.day == 19
    assert remote.remote == "remote"  # the relocation flag does not disturb the mode
    assert remote.location == "Россия, Relocation"


def test_paging_stops_at_the_total_and_resumes_by_offset(search_pages, load_fixture):
    offsets: list[str] = []
    offer = load_fixture("getmatch/offers.json")["offers"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        offsets.append(req.url.params["offset"])
        offers = [{**offer, "id": int(req.url.params["offset"]) + i} for i in range(100)]
        return httpx.Response(200, json={"meta": {"total": 250}, "offers": offers})

    pages = search_pages(GetMatch(), handler, limit=1000)
    assert offsets == ["0", "100", "200"] and len(pages) == 3
    offsets.clear()
    search_pages(GetMatch(), handler, limit=1000, start_page=2)
    assert offsets == ["200"]
    offsets.clear()
    search_pages(GetMatch(), handler, limit=100)
    assert offsets == ["0"]


def test_fetch_details_adds_the_body_and_skills(fetch_details, load_fixture):
    stub = JobStub(
        source="getmatch", title="t", company="c",
        url="https://getmatch.ru/vacancies/34895-senior-golang",
    )  # fmt: skip
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("getmatch/offer_34895.json"))

    out = fetch_details(GetMatch(), handler, stub)
    assert seen == ["/api/offers/34895"]
    assert out.description == "О компании\nFull body\n\nSkills: Go, PostgreSQL"  # noqa: RUF001


def test_it_is_an_opt_in_aggregator():
    assert registry()["getmatch"].kind == "aggregator"
