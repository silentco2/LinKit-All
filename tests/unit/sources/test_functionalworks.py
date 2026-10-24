import json

import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.functionalworks import FunctionalWorks


def test_search_posts_one_graphql_query_and_maps_postings(search_pages, load_fixture):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("functionalworks/jobs.json"))

    (page,) = search_pages(FunctionalWorks(), handler)
    assert len(bodies) == 1 and "page_size:2000" in bodies[0]["query"]
    scala, clojure = page  # the postings without a slug or a company are dropped
    assert (scala.title, scala.company, scala.location) == (
        "Senior Scala Engineer", "Acme", "Berlin, Germany",
    )  # fmt: skip
    assert scala.url == "https://functional.works-hub.com/jobs/remote-senior-scala-engineer-abc"
    assert scala.description == "Build & ship with Scala.\n\nTags: Scala, Kafka"
    assert scala.remote == "remote" and scala.posted_at is not None
    assert (clojure.location, clojure.remote, clojure.description) == (
        "France", None, "Onsite role.",
    )  # fmt: skip


def test_the_task_limit_and_start_page_slice_the_backlog(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        job = load_fixture("functionalworks/jobs.json")["data"]["jobs"][0]
        jobs = [{**job, "slug": f"s{i}"} for i in range(250)]
        return httpx.Response(200, json={"data": {"jobs": jobs}})

    pages = search_pages(FunctionalWorks(), handler, limit=230)
    assert [len(p) for p in pages] == [100, 100, 30]
    pages = search_pages(FunctionalWorks(), handler, limit=230, start_page=2)
    assert [len(p) for p in pages] == [30]


def test_an_empty_answer_yields_nothing(search_pages):
    assert search_pages(FunctionalWorks(), lambda r: httpx.Response(200, json={"data": None})) == []


def test_it_is_an_opt_in_aggregator():
    assert registry()["functionalworks"].kind == "aggregator"
