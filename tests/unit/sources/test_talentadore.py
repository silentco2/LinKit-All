from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.talentadore import TalentAdore
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    urls: list[str] = []
    pages = search_pages(
        TalentAdore(),
        lambda req: httpx.Response(200, json=load_fixture("talentadore/feed.json")),
        board="9wmfASE",
        calls=urls,
    )
    assert urls == ["https://ats.talentadore.com/positions/9wmfASE/json?v=2"]
    assert len(pages) == 1 and len(pages[0]) == 2  # the posting without a token is dropped
    ai, designer = pages[0]
    assert ai.title == "AI Engineer" and ai.company == "Acme Oy"
    assert ai.url == ai.apply_url == "https://ats.talentadore.com/apply/ai-engineer/mWXEgr"
    assert ai.location == "Helsinki, Finland"  # the street address is not used
    assert ai.description == "Build models." and ai.ats == "talentadore"
    assert ai.posted_at is not None and ai.posted_at.isoformat() == "2026-07-10T12:16:20"
    assert ai.extra == {"board": "9wmfASE", "id": "mWXEgr"}
    # no HTML body: the plain-text one is used; no start date: the update date
    assert designer.description == "Design things." and designer.location == "Remote"
    assert designer.remote == "remote"
    assert designer.posted_at is not None and designer.posted_at.date().isoformat() == "2026-07-09"


def test_resume_and_errors(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    assert (
        search_pages(
            TalentAdore(), lambda req: httpx.Response(200, json={}), board="x", start_page=1
        )
        == []
    )
    assert search_pages(TalentAdore(), lambda req: httpx.Response(200, json={}), board="x") == [[]]
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(TalentAdore(), lambda req: httpx.Response(404), board="x")


def test_url_patterns() -> None:
    assert detect("https://ats.talentadore.com/positions/9wmfASE/json") == (
        "talentadore",
        "9wmfASE",
    )
    assert detect("talentadore:9wmfASE") == ("talentadore", "9wmfASE")
