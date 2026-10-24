"""Helpers private to the F1.7 ATS adapters (the underscore keeps it out of the registry)."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeVar

import httpx
from selectolax.lexbor import LexborNode

from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

T = TypeVar("T")
XHR = {"X-Requested-With": "XMLHttpRequest"}  # what the sites' own scripts send with their calls


def text_of(node: LexborNode | None) -> str:
    """The node's text with every run of whitespace (nbsp too) collapsed to one space."""
    return " ".join(node.text(deep=True).split()) if node is not None else ""


def next_element(node: LexborNode) -> LexborNode | None:
    """The next sibling that is an element (a server-rendered table is full of text nodes)."""
    sib = node.next
    while sib is not None and sib.tag == "-text":
        sib = sib.next
    return sib


async def post_form(
    http: Http, url: str, data: Mapping[str, Any], headers: Mapping[str, str] | None = None
) -> httpx.Response:
    """POST an urlencoded form through Http's per-host limiter and retries (it has no helper for
    forms yet). HTTP errors raise."""
    resp = await http._send("POST", url, data=dict(data), headers=dict(headers or {}))
    resp.raise_for_status()
    return resp


async def hydrate(
    items: Sequence[T],
    start_page: int,
    build: Callable[[T], Awaitable[JobStub | None]],
    size: int,
) -> AsyncIterator[list[JobStub]]:
    """Walk `items` `size` at a time from page `start_page`; each page's postings are built
    together (Http paces them per host) and the ones `build` returns None for are left out."""
    for i in range(start_page * size, len(items), size):
        built = await asyncio.gather(*(build(item) for item in items[i : i + size]))
        yield [s for s in built if s is not None]
