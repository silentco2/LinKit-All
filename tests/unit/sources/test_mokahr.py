import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import mokahr
from linkit_all.sources.ats.mokahr import MokaHR, decrypt
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_plain_listing_on_the_international_host(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        assert req.url.host == "hire-r1.mokahr.com"
        return httpx.Response(200, json=load_fixture("mokahr/redotpay_r1.json"))

    pages = search_pages(MokaHR(), handler, board="r1/redotpay/70002")
    assert bodies == [
        {"siteId": 70002, "orgId": "redotpay", "locale": "zh-CN", "limit": 50, "offset": 0}
    ]
    assert len(pages) == 1 and len(pages[0]) == 3
    a = pages[0][0]
    assert a.title == "Head of Infrastructure SRE" and a.company == "Redotpay"
    assert a.url == (
        "https://hire-r1.mokahr.com/social-recruitment/redotpay/70002"
        "#/job/4ba24846-db2b-4660-867b-496b36ade804"
    )
    assert a.location == "Hong Kong" and a.ats == "mokahr" and a.apply_url == a.url
    assert a.description  # the HTML body is stripped to text
    # zone-less timestamps are China time: 2026-10-12 00:00 CST is the evening before in UTC
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-11T16:00:00"
    assert a.extra["id"] == "4ba24846-db2b-4660-867b-496b36ade804"


def test_paused_postings_are_skipped_and_cities_named(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "app.mokahr.com"
        return httpx.Response(200, json=load_fixture("mokahr/moonshot_plain.json"))

    pages = search_pages(MokaHR(), handler, board="moonshot/140576")
    titles = [j.title for j in pages[0]]
    assert titles == [
        "Agentic Commerce Engineer",
        "Global PR｜海外PR内容专家",  # noqa: RUF001
        "Business Builder & Ecosystem",
    ]  # the fourth is paused
    assert (
        pages[0][0].location == "Beijing" and pages[0][2].location == "Shenzhen; Shanghai; Beijing"
    )
    assert pages[0][0].extra["employment"] == "全职"


def test_encrypted_listing_is_read(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture("mokahr/deepseek_encrypted_limit1.json"))

    pages = search_pages(MokaHR(), handler, board="high-flyer/140576")
    assert [j.title for j in pages[0]] == ["研发基础设施工程师"]
    assert pages[0][0].location == "Hangzhou; Beijing"
    assert decrypt(load_fixture("mokahr/deepseek_encrypted_limit1.json"))["success"] is True


def test_changed_scheme_is_an_error(load_fixture: Callable[[str], Any]) -> None:
    env = {**load_fixture("mokahr/deepseek_encrypted_limit1.json"), "necromancer": "0" * 16}
    with pytest.raises(ValueError, match="could not decrypt"):
        decrypt(env)


def test_paging_runs_until_a_short_page_and_resumes(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mokahr, "PAGE_SIZE", 2)
    rows = load_fixture("mokahr/moonshot_plain.json")["data"]["jobs"]
    offsets: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        offset = json.loads(req.content)["offset"]
        offsets.append(offset)
        return httpx.Response(
            200, json={"success": True, "code": 0, "data": {"jobs": rows[offset : offset + 2]}}
        )

    pages = search_pages(MokaHR(), handler, board="moonshot/1")
    assert [len(p) for p in pages] == [2, 1, 0]  # one paused; a full page means ask again
    assert offsets == [0, 2, 4]
    offsets.clear()
    resumed = search_pages(MokaHR(), handler, board="moonshot/1", start_page=1)
    assert offsets == [2, 4] and [len(p) for p in resumed] == [1, 0]


def test_api_error_and_bad_boards(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    refused = {"success": False, "code": 102, "msg": "limit too large"}
    with pytest.raises(ValueError, match="code 102"):
        search_pages(MokaHR(), lambda req: httpx.Response(200, json=refused), board="o/1")
    with pytest.raises(ValueError, match="not <orgId>/<siteId>"):
        search_pages(MokaHR(), lambda req: httpx.Response(200, json={}), board="just-a-slug")


def test_url_patterns() -> None:
    assert detect("https://app.mokahr.com/social-recruitment/moonshot/140576#/jobs") == (
        "mokahr",
        "moonshot/140576",
    )
    assert detect("https://app.mokahr.com/apply/high-flyer/140576") == (
        "mokahr",
        "high-flyer/140576",
    )
    assert detect("https://hire-r1.mokahr.com/social-recruitment/redotpay/70002") == (
        "mokahr",
        "r1/redotpay/70002",
    )
    assert detect("mokahr:moonshot/140576") == ("mokahr", "moonshot/140576")
