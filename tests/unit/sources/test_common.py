import asyncio
from collections.abc import Callable

import httpx
import pytest

from linkit_all.sources.common import absolute, paged, retry_after, retry_while, strip_html


def run_retry(
    statuses: list[tuple[int, dict[str, str]]], **kw: object
) -> tuple[httpx.Response, list[float], int]:
    sleeps: list[float] = []
    calls = 0

    async def call() -> httpx.Response:
        nonlocal calls
        status, headers = statuses[min(calls, len(statuses) - 1)]
        calls += 1
        return httpx.Response(status, headers=headers)

    async def sleep(s: float) -> None:
        sleeps.append(s)

    resp = asyncio.run(retry_while(call, sleep=sleep, **kw))  # type: ignore[arg-type]
    return resp, sleeps, calls


def test_retry_backoff_doubles_and_caps() -> None:
    resp, sleeps, calls = run_retry([(429, {})], attempts=5, base_delay=1, max_delay=3)
    assert (resp.status_code, calls, sleeps) == (429, 5, [1, 2, 3, 3])


def test_retry_stops_on_success_and_on_other_statuses() -> None:
    resp, sleeps, calls = run_retry([(403, {}), (200, {})])
    assert (resp.status_code, calls, sleeps) == (200, 2, [1])
    resp, sleeps, calls = run_retry([(500, {})])  # not in retry_on: caller deals with it
    assert (resp.status_code, calls, sleeps) == (500, 1, [])
    _, sleeps, calls = run_retry([(500, {}), (200, {})], retry_on=(500,))
    assert (calls, sleeps) == (2, [1])


def test_retry_honors_retry_after() -> None:
    resp, sleeps, calls = run_retry([(429, {"Retry-After": "7"}), (200, {})])
    assert (resp.status_code, sleeps) == (200, [7.0])
    # longer than max_delay: do not hammer the server, hand the 429 back at once
    resp, sleeps, calls = run_retry([(429, {"Retry-After": "300"})], max_delay=30)
    assert (resp.status_code, sleeps, calls) == (429, [], 1)


def test_retry_after_parsing() -> None:
    def hdr(v: str) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": v})

    assert retry_after(httpx.Response(429)) is None
    assert retry_after(hdr("2.5")) == 2.5
    assert retry_after(hdr("nonsense")) is None
    assert retry_after(hdr("Wed, 21 Oct 2015 07:28:00 GMT")) == 0.0  # in the past


def test_retry_needs_an_attempt() -> None:
    with pytest.raises(ValueError):
        run_retry([(200, {})], attempts=0)


def drain(
    pages: list[list[int]], size: int, total: int | None, start: int = 0
) -> tuple[list[list[int]], list[int]]:
    rows = [i for p in pages for i in p]
    offsets: list[int] = []

    async def fetch(offset: int) -> tuple[list[int], int | None]:
        offsets.append(offset)
        return rows[offset : offset + size], total

    async def go() -> list[list[int]]:
        return [p async for p in paged(fetch, size, start)]

    return asyncio.run(go()), offsets


def test_paged_walks_until_short_page() -> None:
    out, offsets = drain([[1, 2], [3, 4], [5]], 2, None)
    assert out == [[1, 2], [3, 4], [5]] and offsets == [0, 2, 4]


def test_paged_stops_at_total_and_on_empty() -> None:
    out, offsets = drain([[1, 2], [3, 4], [5, 6]], 2, 4)
    assert out == [[1, 2], [3, 4]] and offsets == [0, 2]
    out, offsets = drain([[1, 2], [3, 4]], 2, None)  # full last page -> one empty fetch
    assert out == [[1, 2], [3, 4]] and offsets == [0, 2, 4]


def test_paged_resumes_and_caps() -> None:
    out, offsets = drain([[1, 2], [3, 4], [5]], 2, None, start=1)
    assert out == [[3, 4], [5]] and offsets == [2, 4]

    async def forever(offset: int) -> tuple[list[int], int | None]:
        return [1], None

    async def go() -> int:
        return len([p async for p in paged(forever, 1, max_pages=7)])

    assert asyncio.run(go()) == 7


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("/jobs/1", "https://x.io/jobs/1"),
        ("jobs/1", "https://x.io/a/jobs/1"),
        ("//cdn.x.io/a", "https://cdn.x.io/a"),
        ("https://y.io/z", "https://y.io/z"),
        ("", ""),
        (None, ""),
    ],
)
def test_absolute(url: str | None, expected: str) -> None:
    assert absolute(url, "https://x.io/a/b") == expected


def test_strip_html() -> None:
    f: Callable[[str], str] = strip_html
    assert f("<p>Hello <b>world</b></p><script>x()</script>") == "Hello\nworld"
    assert strip_html("&lt;p&gt;Hi&lt;/p&gt;", escaped=True) == "Hi"
