import json

import httpx
import pytest

from linkit_all.sources.ats.redrover import RedRover
from linkit_all.sources.ats_detector import detect


def test_search_keeps_public_open_postings(search_pages, load_fixture):
    data = load_fixture("redrover/postings.json")
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://api.redroverk12.com/graphql"
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=data)

    ((job,),) = search_pages(RedRover(), handler, board="4242")
    assert sent[0]["variables"]["search"]["orgId"] == "4242"
    assert (job.title, job.company, job.location) == (
        "Math Teacher",
        "Lakeside Unified",
        "Lakeside High",
    )
    assert job.url == "https://jobs.redroverk12.com/org/4242/opening/901" and job.remote is None
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-10-01T00:00:00"


def test_a_board_past_the_one_page_fails_loudly(search_pages, load_fixture):
    data = load_fixture("redrover/postings.json")
    data["data"]["jobSeekerSiteUnauthenticated"]["jobPostingSearch"]["hasMoreData"] = True
    with pytest.raises(ValueError, match="more than 500"):
        search_pages(RedRover(), lambda req: httpx.Response(200, json=data), board="4242")


def test_url_patterns():
    assert detect("https://jobs.redroverk12.com/org/4242/opening/901") == ("redrover", "4242")
