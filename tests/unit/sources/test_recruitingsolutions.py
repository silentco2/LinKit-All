import json

import httpx

from linkit_all.sources.ats import recruitingsolutions
from linkit_all.sources.ats.recruitingsolutions import RecruitingSolutions, split_id


def _handler(load_fixture, seen):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        body = json.loads(req.content)
        seen.append((req.headers["customerId"], body["skip"]))
        return httpx.Response(
            200,
            json=load_fixture(
                f"recruitingsolutions/page{body['skip'] // recruitingsolutions.PAGE + 1}.json"
            ),
        )

    return handler


def test_split_id():
    assert split_id("274342-en_GB") == ("274342", "en_GB")
    assert split_id("274342") == ("274342", "")


def test_search_dedups_locales_across_pages(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(recruitingsolutions, "PAGE", 2)
    seen: list[tuple[str, int]] = []
    pages = search_pages(RecruitingSolutions(), _handler(load_fixture, seen), board="riv-prod")
    assert seen == [("riv-prod", 0), ("riv-prod", 2)]
    jobs = {s.extra["id"]: s for p in pages for s in p}
    assert set(jobs) == {"100", "200"}  # 300 is inactive
    eng = jobs["100"]
    assert (eng.title, eng.company, eng.location) == (
        "Engineer",
        "Riverty Group GmbH",
        "Berlin, Germany",
    )
    assert (
        eng.url == "https://jobsearch.createyourowncareer.com/job-invite/100/"
    )  # locale query dropped
    assert eng.remote == "hybrid" and eng.description == "Body" and eng.ats == "recruitingsolutions"
    assert eng.posted_at is not None and eng.posted_at.year == 2026
    assert jobs["200"].remote == "onsite" and jobs["200"].title == "Buchhalter"  # only locale: kept
