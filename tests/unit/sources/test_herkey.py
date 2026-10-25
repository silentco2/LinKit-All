import json

import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.herkey import HerKey
from linkit_all.sources.base import JobStub

API = "/api/v1/herkey/"


def _list_handler(load_fixture, tokens=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == API + "generate-session":
            return httpx.Response(200, json={"body": {"session_id": "tok"}})
        assert req.url.path == API + "jobs/es_candidate_jobs"
        if tokens is not None:
            tokens.append(req.headers["Authorization"])
        return httpx.Response(
            200, json=load_fixture(f"herkey/herkey_list_page{req.url.params['page_no']}.json")
        )

    return handler


def test_search_walks_the_listing_with_the_session_token(search_pages, load_fixture):
    tokens: list[str] = []
    pages = search_pages(
        HerKey(), _list_handler(load_fixture, tokens), limit=300, posted_within_days=36500
    )
    assert tokens == ["Token tok", "Token tok"]  # two listing pages
    stubs = [s for p in pages for s in p]
    assert [s.extra["id"] for s in stubs] == [
        194415,
        194409,
        194271,
        193866,
        179885,
    ]  # newest first
    pm = stubs[0]
    assert (pm.title, pm.company, pm.location, pm.remote) == (
        "Project Manager", "IT Exchange", "", "remote",
    )  # fmt: skip
    assert pm.url == "https://www.herkey.com/jobs/project-manager/194415" and pm.apply_url == pm.url
    assert (pm.posted_at.hour, pm.posted_at.minute) == (11, 33)  # 17:03 India time
    aristocrat = next(s for s in stubs if s.company == "Aristocrat")
    assert aristocrat.location == "Noida" and aristocrat.remote is None
    assert aristocrat.apply_url.startswith("https://aristocrat.wd3.myworkdayjobs.com/")  # unwrapped


def test_the_task_limit_keeps_the_newest(search_pages, load_fixture):
    pages = search_pages(HerKey(), _list_handler(load_fixture), limit=2, posted_within_days=36500)
    assert [s.extra["id"] for p in pages for s in p] == [194415, 194409]


def _detail_handler(load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        job_id = req.url.path.rsplit("/", 1)[-1]
        if job_id == "404":
            return httpx.Response(404)
        return httpx.Response(200, json=load_fixture(f"herkey/herkey_detail_{job_id}.json"))

    return handler


def _stub(job_id: int) -> JobStub:
    return JobStub(
        source="herkey", url=f"https://www.herkey.com/jobs/x/{job_id}", title="t", company="c"
    )


def test_fetch_details_joins_the_body_parts(fetch_details, load_fixture):
    done = fetch_details(HerKey(), _detail_handler(load_fixture), _stub(194415))
    assert "ITeXchange" in done.description and "Desired Skills and Experience" in done.description
    assert done.posted_at is not None and done.posted_at.day == 14


def test_fetch_details_keeps_the_stub_when_the_job_is_gone(fetch_details, load_fixture):
    handler = _detail_handler(load_fixture)
    assert fetch_details(HerKey(), handler, _stub(179885)).description == ""  # inactive
    assert fetch_details(HerKey(), handler, _stub(404)).description == ""  # 404


def test_fetch_details_skips_placeholder_bodies(fetch_details):
    body = {"body": [{"id": 7, "status": "active", "description": '"TBD"', "responsibilities": "None",
                      "requirements": "Know Python"}]}  # fmt: skip
    handler = lambda req: httpx.Response(200, content=json.dumps(body))  # noqa: E731
    assert fetch_details(HerKey(), handler, _stub(7)).description == "Know Python"


def test_it_is_an_opt_in_aggregator():
    assert registry()["herkey"].kind == "aggregator"
