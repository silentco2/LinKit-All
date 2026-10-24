"""Small helpers private to the F1.3 ATS adapters (the underscore keeps it out of the registry)."""

import asyncio
import re
from collections.abc import Callable
from typing import TypeVar

import httpx

from linkit_all.sources.base import Remote
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http

T = TypeVar("T")
_MODES: dict[str, Remote] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "on site": "onsite",
    "office": "onsite",
}
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)


async def get_page(http: Http, url: str) -> httpx.Response:
    """GET a human-facing page: robots.txt is checked first and a refusal stops the board with
    a readable message. HTTP errors raise (the runner records them)."""
    if not await http.allowed(url):
        raise Unsupported(f"robots.txt does not allow fetching {url}")
    resp = await http.get(url)
    resp.raise_for_status()
    return resp


def mode(value: str | None) -> Remote | None:
    """A vendor's workplace-type word ("Hybrid", "ON_SITE", "Office") as our remote mode."""
    return _MODES.get((value or "").strip().lower().replace("_", "-"))


def name_from_slug(slug: str) -> str:
    """Display name for a board slug when the API gives none: "acme-corp" -> "Acme Corp"."""
    return slug.replace("-", " ").replace("_", " ").title()


def name_from_host(host: str) -> str:
    """Company name from a careers host: "jobs.acme.com" -> "Acme", "acme.eploy.net" -> "Acme"."""
    skip = ("www", "jobs", "careers", "career")
    labels = [p for p in host.lower().split(".") if p not in skip]
    return name_from_slug(labels[0] if labels else host)


def sitemap_locs(xml: str) -> list[str]:
    """Every <loc> of a sitemap, in order, unescaped."""
    return [u.replace("&amp;", "&") for u in _LOC.findall(xml)]


async def fetch_all(http: Http, urls: list[str], parse: Callable[[str, str], T | None]) -> list[T]:
    """GET every page together (Http paces them per host) and map `parse(html, url)` over the
    ones that exist and parse; a page that is gone (404/410) or parses to None is left out."""

    async def one(url: str) -> T | None:
        try:
            resp = await get_page(http, url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 410):
                return None
            raise
        return parse(resp.text, url)

    return [r for r in await asyncio.gather(*(one(u) for u in urls)) if r is not None]
