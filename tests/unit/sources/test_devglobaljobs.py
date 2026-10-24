import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.devglobaljobs import DevGlobalJobs
from linkit_all.sources.base import JobStub


def test_search_maps_postings_and_keeps_the_id_in_the_url(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("devglobaljobs/list.json"))

    (page,) = search_pages(DevGlobalJobs(), handler, posted_within_days=3650)
    assert dict(seen[0].url.params) == {"limit": "100", "offset": "0"}
    first, second = page  # the posting without an id is dropped
    assert (first.title, first.company, first.location) == (
        "Senior Software Engineer, Storage", "Airbnb", "San Francisco, CA",
    )  # fmt: skip
    assert first.url == "https://devglobaljobs.com/jobs/detail/165923983"
    assert first.description == "" and first.remote is None  # the body comes from fetch_details
    assert first.posted_at is not None and first.posted_at.day == 20
    assert second.remote == "remote"
    assert second.url.endswith("/165916167")
    assert second.apply_url == "https://acme.example/apply/42"


def test_paging_follows_has_more_and_resumes_by_offset(search_pages, load_fixture):
    offsets: list[str] = []
    row = load_fixture("devglobaljobs/list.json")["jobs"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        offsets.append(req.url.params["offset"])
        jobs = [{**row, "id": 1000 + len(offsets) * 1000 + i} for i in range(100)]
        return httpx.Response(200, json={"meta": {"hasMore": len(offsets) < 2}, "jobs": jobs})

    pages = search_pages(DevGlobalJobs(), handler, posted_within_days=3650)
    assert offsets == ["0", "100"] and [len(p) for p in pages] == [100, 100]
    offsets.clear()
    search_pages(DevGlobalJobs(), handler, start_page=1, posted_within_days=3650)
    assert offsets[0] == "100"


def test_fetch_details_decodes_the_escaped_body(fetch_details, load_fixture):
    stub = JobStub(
        source="devglobaljobs", title="t", company="c",
        url="https://devglobaljobs.com/jobs/detail/165923983",
    )  # fmt: skip
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("devglobaljobs/detail.json"))

    out = fetch_details(DevGlobalJobs(), handler, stub)
    assert seen == ["/api/v1/jobs/165923983"]
    assert out.description == "Full detailed description from API"


def test_it_is_an_opt_in_aggregator():
    assert registry()["devglobaljobs"].kind == "aggregator"
