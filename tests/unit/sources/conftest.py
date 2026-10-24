"""Shared helpers for per-plugin source tests: `tests/unit/sources/test_<name>.py`.

Fixtures (trimmed real responses) live in `tests/fixtures/<name>/`. Typical test:

    def test_search(search_pages, load_fixture):
        data = load_fixture("acme/jobs.json")
        pages = search_pages(Acme(), lambda req: httpx.Response(200, json=data), board="acme")
        assert pages[0][0].title == "..."
"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def load_fixture() -> Callable[[str], Any]:
    """`load_fixture("name/file.json")` -> parsed JSON; any other extension -> text."""

    def load(name: str) -> Any:
        text = (FIXTURES / name).read_text("utf-8")
        return json.loads(text) if name.endswith(".json") else text

    return load


@pytest.fixture
def mock_transport() -> Callable[[Handler, list[str] | None], httpx.MockTransport]:
    """`mock_transport(handler, calls)`: a MockTransport that also appends each URL to `calls`."""

    def make(handler: Handler, calls: list[str] | None = None) -> httpx.MockTransport:
        def wrapped(req: httpx.Request) -> httpx.Response:
            if calls is not None:
                calls.append(str(req.url))
            return handler(req)

        return httpx.MockTransport(wrapped)

    return make


@pytest.fixture
def search_pages(
    mock_transport: Callable[[Handler, list[str] | None], httpx.MockTransport],
) -> Callable[..., list[list[JobStub]]]:
    """`search_pages(source, handler, board="", query="", start_page=0, calls=None, **task)`
    runs `source.search` against the handler and returns every page of stubs."""

    def run(
        source: Source,
        handler: Handler,
        *,
        board: str = "",
        query: str = "",
        start_page: int = 0,
        calls: list[str] | None = None,
        **task: Any,
    ) -> list[list[JobStub]]:
        async def go() -> list[list[JobStub]]:
            async with httpx.AsyncClient(transport=mock_transport(handler, calls)) as client:
                t = Task(
                    source.name, f"{source.name}:{board or query}", board=board, query=query, **task
                )
                return [p async for p in source.search(Http(client, attempts=1), t, start_page)]

        return asyncio.run(go())

    return run


@pytest.fixture
def fetch_details(
    mock_transport: Callable[[Handler, list[str] | None], httpx.MockTransport],
) -> Callable[..., JobStub]:
    """`fetch_details(source, handler, stub)` -> the stub after `source.fetch_details`."""

    def run(source: Source, handler: Handler, stub: JobStub) -> JobStub:
        async def go() -> JobStub:
            async with httpx.AsyncClient(transport=mock_transport(handler, None)) as client:
                return await source.fetch_details(Http(client, attempts=1), stub)

        return asyncio.run(go())

    return run
