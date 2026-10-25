"""Test plumbing for the F3.2 board plugins: a fast `Http` (the default 2 req/s limit would make
pages of 20 postings slow) and a router from URL fragments to responses."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http

Routes = dict[str, Any]  # URL fragment -> text | bytes | (status, text) | callable(request)


def router(
    routes: Routes, calls: list[httpx.Request] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    """The first route whose key is in the URL answers (longest key first); robots.txt is 404."""

    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req)
        url = str(req.url)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        for key in sorted(routes, key=len, reverse=True):
            if key in url:
                value = routes[key]
                if callable(value):
                    return value(req)  # type: ignore[no-any-return]
                status, body = value if isinstance(value, tuple) else (200, value)
                return httpx.Response(
                    status, content=body if isinstance(body, bytes) else body.encode()
                )
        return httpx.Response(404)

    return handler


def http_for(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[httpx.AsyncClient, Http]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, Http(client, default_rate=1000, attempts=1)


def run_search(
    source: Source,
    handler: Callable[[httpx.Request], httpx.Response],
    start_page: int = 0,
    **task: Any,
) -> list[list[JobStub]]:
    async def go() -> list[list[JobStub]]:
        client, http = http_for(handler)
        async with client:
            t = Task(source.name, f"{source.name}:t", **task)
            return [p async for p in source.search(http, t, start_page)]

    return asyncio.run(go())


def run_details(
    source: Source, handler: Callable[[httpx.Request], httpx.Response], stub: JobStub
) -> JobStub:
    async def go() -> JobStub:
        client, http = http_for(handler)
        async with client:
            return await source.fetch_details(http, stub)

    return asyncio.run(go())
