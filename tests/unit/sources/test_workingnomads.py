import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.workingnomads import WorkingNomads


def _feed(load_fixture):
    return lambda req: httpx.Response(200, json=load_fixture("workingnomads/feed.json"))


def test_search_maps_the_feed_and_takes_the_id_from_the_url(search_pages, load_fixture):
    (page,) = search_pages(WorkingNomads(), _feed(load_fixture))
    (job,) = page  # the URL without a numeric tail is dropped
    assert (job.title, job.company, job.location) == (
        "Senior React Native Developer", "Lemon.io", "Europe, North America",
    )  # fmt: skip
    assert job.url == "https://www.workingnomads.com/job/go/1663269/"
    assert job.extra == {"id": "1663269"} and job.remote == "remote"
    assert job.description == "Build apps." and job.posted_at is not None


def test_one_page_only(search_pages, load_fixture):
    assert search_pages(WorkingNomads(), _feed(load_fixture), start_page=1) == []


def test_it_is_an_opt_in_aggregator():
    assert registry()["workingnomads"].kind == "aggregator"
