"""Workday: the 2,000-job cap split, 403/429 backoff and the shared myworkdaysite.com host.

All JSON here is SYNTHETIC (hand-built minimal responses shaped like Workday's cxs list endpoint,
including its habits: `total` only on the first page, exactly 2000 for a capped board).
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources import workday
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.workday import CAP, Workday, WorkdayCapped

BOARD = "acme/wd5/Careers"
HOST = "acme.wd5.myworkdayjobs.com"
SHARED = "wd1.myworkdaysite.com/snapchat/snap"


def posting(n: int) -> dict[str, Any]:
    return {
        "title": f"Job {n}",
        "externalPath": f"/job/Cairo/Job-{n}_R{n}",
        "locationsText": "Cairo",
        "postedOn": "Posted Today",
        "bulletFields": [f"R{n}"],
    }


def capped(*facets: tuple[str, list[tuple[str, int]]]) -> dict[str, Any]:
    """A first page that reports the cap and offers these facet dimensions."""
    return {
        "total": CAP,
        "jobPostings": [posting(0)],
        "facets": [
            {"facetParameter": name, "values": [{"id": i, "count": c} for i, c in values]}
            for name, values in facets
        ],
    }


Routes = dict[str, Any]  # appliedFacets (JSON) -> a ready page (dict) or the postings to page


def key(**facets: list[str]) -> str:
    return json.dumps(facets, sort_keys=True)


def serve(routes: Routes, seen: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body["appliedFacets"])
        route = routes[json.dumps(body["appliedFacets"], sort_keys=True)]  # KeyError = bad slice
        if isinstance(route, dict):
            return httpx.Response(200, json=route)
        off = body["offset"]  # like the real API, only the first page reports a total
        rows = route[off : off + body["limit"]]
        return httpx.Response(
            200, json={"total": len(route) if off == 0 else 0, "jobPostings": rows}
        )

    return handler


def run(
    handler: Callable[[httpx.Request], httpx.Response], board: str = BOARD, start_page: int = 0
) -> list[JobStub]:
    async def go() -> list[JobStub]:
        host = workday._board(board)[0]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            http = Http(client, per_host_rate={host: 1000.0}, attempts=1)
            task = Task("workday", "k", board=board)
            return [
                s
                for page in [p async for p in Workday().search(http, task, start_page)]
                for s in page
            ]

    return asyncio.run(go())


def test_capped_board_splits_by_facet_and_dedupes() -> None:
    seen: list[dict[str, Any]] = []
    routes: Routes = {
        key(): capped(
            ("big", [("b1", 1500), ("b2", 500)]),
            ("small", [("s1", 3), ("s2", 3)]),  # smallest biggest value: the one to split on
        ),
        key(small=["s1"]): [posting(1), posting(2), posting(3)],
        key(small=["s2"]): [posting(3), posting(4), posting(5)],  # 3 is in both slices
    }
    stubs = run(serve(routes, seen))
    assert [s.extra["req_id"] for s in stubs] == ["R1", "R2", "R3", "R4", "R5"]
    assert seen == [{}, {"small": ["s1"]}, {"small": ["s2"]}]
    assert stubs[0].url == f"https://{HOST}/Careers/job/Cairo/Job-1_R1"


def test_still_capped_slice_splits_again_without_reusing_a_dimension() -> None:
    seen: list[dict[str, Any]] = []
    routes: Routes = {
        key(): capped(("fam", [("f1", 2000)])),
        # the facets of a scoped response still list `fam`; it must not be applied twice
        key(fam=["f1"]): capped(("fam", [("f1", 2000)]), ("sub", [("x", 2), ("y", 1)])),
        key(fam=["f1"], sub=["x"]): [posting(1), posting(2)],
        key(fam=["f1"], sub=["y"]): [posting(3)],
    }
    stubs = run(serve(routes, seen))
    assert [s.extra["req_id"] for s in stubs] == ["R1", "R2", "R3"]
    assert seen == [
        {},
        {"fam": ["f1"]},
        {"fam": ["f1"], "sub": ["x"]},
        {"fam": ["f1"], "sub": ["y"]},
    ]


def test_slice_still_capped_at_depth_three_raises() -> None:
    seen: list[dict[str, Any]] = []
    routes: Routes = {
        key(): capped(("a", [("a1", 2000)])),
        key(a=["a1"]): capped(("b", [("b1", 2000)])),
        key(a=["a1"], b=["b1"]): capped(("c", [("c1", 2000)])),
        key(a=["a1"], b=["b1"], c=["c1"]): capped(("d", [("d1", 2000)])),
    }
    with pytest.raises(WorkdayCapped, match="3 facet dimensions deep"):
        run(serve(routes, seen))
    assert len(seen) == 4  # no fourth dimension was tried


def test_capped_without_a_usable_dimension_raises() -> None:
    routes: Routes = {key(): {"total": CAP, "jobPostings": [posting(1)], "facets": []}}
    with pytest.raises(WorkdayCapped, match="no facet dimension"):
        run(serve(routes, []))


def test_total_is_latched_from_the_first_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workday, "PAGE", 2)
    seen: list[dict[str, Any]] = []
    rows = [posting(n) for n in range(4)]

    def handler(req: httpx.Request) -> httpx.Response:
        off = json.loads(req.content)["offset"]
        seen.append({"offset": off})
        assert off < 4, "paged past the latched total"
        # total only on page 1, and the last page is full: only the latch knows to stop
        return httpx.Response(
            200, json={"total": 4 if off == 0 else 0, "jobPostings": rows[off : off + 2]}
        )

    assert len(run(handler)) == 4
    assert seen == [{"offset": 0}, {"offset": 2}]


def test_resume_into_a_capped_board_skips_stored_pages() -> None:
    routes: Routes = {
        key(): capped(("d", [("d1", 2), ("d2", 1)])),
        key(d=["d1"]): [posting(1), posting(2)],
        key(d=["d2"]): [posting(3)],
    }
    # start_page=1: the probe sees the cap, the split is re-walked and page 0 is not yielded again
    stubs = run(serve(routes, []), start_page=1)
    assert [s.extra["req_id"] for s in stubs] == ["R3"]


def patched_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []

    async def nap(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(workday, "_nap", nap)
    return sleeps


def test_403_then_200_retries_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = patched_sleep(monkeypatch)
    replies = iter([403, 403, 200])

    def handler(req: httpx.Request) -> httpx.Response:
        status = next(replies)
        return httpx.Response(status, json={"total": 1, "jobPostings": [posting(1)]})

    assert len(run(handler)) == 1
    assert sleeps == [1.0, 2.0]


def test_429_honours_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = patched_sleep(monkeypatch)
    replies = iter([httpx.Response(429, headers={"Retry-After": "7"}), None])

    def handler(req: httpx.Request) -> httpx.Response:
        return next(replies) or httpx.Response(200, json={"total": 1, "jobPostings": [posting(1)]})

    assert len(run(handler)) == 1
    assert sleeps == [7.0]


def test_endless_403_gives_up_after_six_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = patched_sleep(monkeypatch)
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(403)

    with pytest.raises(RetryableStatus):
        run(handler)
    assert len(calls) == 7 and sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]


def test_details_are_retried_too(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = patched_sleep(monkeypatch)
    replies = iter([403, 200])

    def handler(req: httpx.Request) -> httpx.Response:
        status = next(replies)
        return httpx.Response(status, json={"jobPostingInfo": {"jobDescription": "<p>Hello</p>"}})

    async def go() -> JobStub:
        stub = Workday.stub(posting(1), BOARD, "Acme")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            http = Http(client, per_host_rate={HOST: 1000.0}, attempts=1)
            return await Workday().fetch_details(http, stub)

    assert asyncio.run(go()).description == "Hello" and sleeps == [1.0]


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("https://wd1.myworkdaysite.com/recruiting/snapchat/snap", SHARED),
        ("https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap/job/Remote/Eng_R1", SHARED),
        ("https://wd3.myworkdaysite.com/wday/cxs/acme/ext/jobs", "wd3.myworkdaysite.com/acme/ext"),
        ("workday:wd1.myworkdaysite.com/snapchat/snap", SHARED),
        ("https://acme.wd5.myworkdayjobs.com/en-US/Careers", BOARD),  # per-tenant form still works
    ],
)
def test_detector_knows_both_host_shapes(text: str, slug: str) -> None:
    assert detect(text) == ("workday", slug)


def test_shared_host_board_urls_and_details() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.url.host}{req.url.path}")
        if req.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": [posting(1)]})
        return httpx.Response(200, json={"jobPostingInfo": {"jobDescription": "<p>Hi</p>"}})

    stubs = run(handler, board=SHARED)
    assert (
        stubs[0].url == "https://wd1.myworkdaysite.com/recruiting/snapchat/snap/job/Cairo/Job-1_R1"
    )
    assert stubs[0].company == "Snapchat"

    async def go() -> JobStub:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            http = Http(client, per_host_rate={"wd1.myworkdaysite.com": 1000.0}, attempts=1)
            return await Workday().fetch_details(http, stubs[0])

    assert asyncio.run(go()).description == "Hi"
    assert seen == [
        "wd1.myworkdaysite.com/wday/cxs/snapchat/snap/jobs",
        "wd1.myworkdaysite.com/wday/cxs/snapchat/snap/job/Cairo/Job-1_R1",
    ]
