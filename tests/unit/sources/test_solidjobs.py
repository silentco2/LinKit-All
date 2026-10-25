import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.solidjobs import SolidJobs


def _ok(load_fixture):
    return lambda req: httpx.Response(200, json=load_fixture("solidjobs/it.json"))


def test_search_maps_postings_and_sends_the_campaign(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return _ok(load_fixture)(req)

    (page,) = search_pages(SolidJobs(), handler, board="it")
    assert seen[0].url.path == "/public-api/offers/it" and seen[0].url.params["campaign"]
    devops, qa = page  # the posting without a key is dropped
    assert (devops.title, devops.company, devops.location) == (
        "DevOps Engineer", "Sollers Consulting", "Bydgoszcz",
    )  # fmt: skip
    assert devops.url == "https://solid.jobs/o/s6evgozq/linkit"
    assert devops.remote == "hybrid" and "Build pipelines." in devops.description
    assert "x()" not in devops.description and "Skills: Docker, Kubernetes" in devops.description
    assert devops.posted_at is not None and devops.posted_at.day == 10
    assert (qa.remote, qa.location) == ("remote", "Warsaw, Krakow")


def test_one_task_per_division_and_no_resume(search_pages, load_fixture):
    (task,) = SolidJobs().tasks(SearchConfig())
    assert task.board == "it" and task.key == "solidjobs:it"
    assert search_pages(SolidJobs(), _ok(load_fixture), board="it", start_page=1) == []


def test_it_is_an_opt_in_aggregator():
    assert registry()["solidjobs"].kind == "aggregator"
