import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.remotive import Remotive


def _ok(data):
    return lambda req: httpx.Response(200, json=data)


def test_search_reads_the_feed_with_a_single_request(search_pages, load_fixture):
    calls: list[str] = []
    ((first, second, third),) = search_pages(
        Remotive(), _ok(load_fixture("remotive/jobs.json")), calls=calls
    )
    assert len(calls) == 1  # the API is rate-limited: never paged, never repeated
    assert (first.title, first.company, first.location) == (
        "AI Trainer - Video Annotation",
        "iMerit Technology",
        "Worldwide",
    )
    assert first.url == (
        "https://remotive.com/remote-jobs/artificial-intelligence/ai-trainer-video-annotation-2091161"
    )
    assert first.apply_url == first.url and first.extra == {"id": "2091161"}
    assert first.remote == "remote"
    assert first.posted_at is not None and first.posted_at.isoformat() == "2026-10-22T18:40:19"
    assert "<" not in first.description
    assert second.company == "Askable" and third.location == "USA, Canada, USA timezones"


def test_limit_resume_and_unusable_rows(search_pages, load_fixture):
    data = load_fixture("remotive/jobs.json")
    assert len(search_pages(Remotive(), _ok(data), limit=2)[0]) == 2
    assert search_pages(Remotive(), _ok(data), start_page=1) == []
    data["jobs"][0]["id"], data["jobs"][1]["company_name"] = 0, ""
    assert [s.company for s in search_pages(Remotive(), _ok(data))[0]] == ["Mitre Media"]


def test_it_is_an_opt_in_aggregator_with_one_feed_task():
    source = registry()["remotive"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a", "b"]}, "sources": {"enabled": ["remotive"]}}
    )
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1
