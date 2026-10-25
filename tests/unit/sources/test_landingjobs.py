import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.landingjobs import LandingJobs, company_from_url


def _ok(data):
    return lambda req: httpx.Response(200, json=data)


def test_search_maps_the_feed(search_pages, load_fixture):
    ((java, de, ai),) = search_pages(LandingJobs(), _ok(load_fixture("landingjobs/jobs.json")))
    assert (java.title, java.company, java.location) == (
        "Senior Java Software Developer",
        "Inscale",
        "Lisbon, PT",
    )
    assert (
        java.url == "https://landing.jobs/at/inscale/senior-java-software-developer-in-lisbon-2025"
    )
    assert java.extra == {"id": 19066} and java.remote is None
    assert java.posted_at is not None and java.posted_at.year == 2025
    assert "Requirements" in java.description and "Perks" in java.description
    assert "<" not in java.description
    assert (java.salary_min, java.salary_max) == (50000, 67000)
    assert (java.salary_currency, java.salary_interval) == ("EUR", "year")
    assert de.company == "Ki Performance"
    assert de.location == "Munich, DE; Lisbon, PT; Cologne, DE"  # every city, not the first
    assert ai.title.startswith("Senior AI Engineer")


def test_remote_flag_adds_remote_to_the_location_and_unusable_rows_are_dropped(
    search_pages, load_fixture
):
    data = load_fixture("landingjobs/jobs.json")
    data[0]["remote"], data[0]["locations"] = True, None
    data[1]["url"] = "https://landing.jobs/at/ki-performance"  # a company page, not a posting
    first, last = search_pages(LandingJobs(), _ok(data))[0]
    assert (first.location, first.remote) == ("Remote", "remote")
    assert last.extra["id"] == 19412


def test_limit_caps_the_feed_and_resume_skips_it(search_pages, load_fixture):
    handler = _ok(load_fixture("landingjobs/jobs.json"))
    assert len(search_pages(LandingJobs(), handler, limit=2)[0]) == 2
    assert search_pages(LandingJobs(), handler, start_page=1) == []


def test_company_from_url():
    assert company_from_url("https://landing.jobs/at/acme-corp/senior-go") == "Acme Corp"
    assert company_from_url("https://landing.jobs/at/gitHub/x?utm=1") == "GitHub"
    assert company_from_url("https://landing.jobs/at/acme-corp") == ""
    assert company_from_url("https://landing.jobs/jobs/1") == ""


def test_it_is_an_opt_in_aggregator():
    source = registry()["landingjobs"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a"]}, "sources": {"enabled": ["landingjobs"]}}
    )
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1
