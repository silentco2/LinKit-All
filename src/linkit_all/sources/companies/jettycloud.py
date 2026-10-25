"""JettyCloud's own careers site (jettycloud.com/vacancies): the employer runs no ATS a crawl can
reach, and the Next.js site's GraphQL endpoint is not public, so a posting is read from the Apollo
cache Next.js embeds in its page (__NEXT_DATA__); the body is Editor.js blocks. A single-company
plugin, not an ATS. Logic adapted from freehire (MIT)."""

import html
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, hydrate, page_text, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import links, next_data

HOST = "www.jettycloud.com"
PREFIX = "/vacancies/"
CHUNK = 10


def _slug(url: str) -> str:
    return urlsplit(url).path.removeprefix(PREFIX).strip("/")


def editor_html(content: str) -> str:
    """Editor.js blocks (stored as a JSON string) as HTML. Block text already carries inline HTML;
    a list item is plain text. Unknown block types are dropped, not fatal."""
    try:
        blocks = json.loads(content or "[]")
    except ValueError:
        return ""
    out: list[str] = []
    for b in blocks if isinstance(blocks, list) else []:
        data = b.get("data") or {}
        kind, text = b.get("type"), data.get("text") or ""
        if kind == "paragraph" and text:
            out.append(f"<p>{text}</p>")
        elif kind == "header" and text:
            level = data.get("level")
            tag = f"h{level}" if level in (2, 3, 4) else "h3"
            out.append(f"<{tag}>{text}</{tag}>")
        elif kind == "list" and data.get("items"):
            items = "".join(f"<li>{html.escape(i)}</li>" for i in data["items"])
            out.append(f"<ul>{items}</ul>")
    return "".join(out)


def vacancy(page: str, slug: str) -> dict[str, Any] | None:
    """The page's own vacancy. Its Apollo cache also holds the related ones, so the entry is
    picked by the slug the page was fetched under. None for a closed posting (it keeps its URL,
    answers 200 and drops out of the cache)."""
    state = (
        ((next_data(page) or {}).get("props") or {}).get("pageProps", {}).get("initialApolloState")
    )
    for key, entry in (state or {}).items():
        if key.startswith("Vacancy:") and isinstance(entry, dict) and entry.get("slug") == slug:
            return entry
    return None


class JettyCloud(Source):
    name = "jettycloud"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "jettycloud:vacancies", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = f"https://{task.board}{PREFIX}"
        # Anchors only: the view switcher's CSS also names /vacancies/grid_icon.svg.
        urls = links(
            (await get_page(http, f"https://{task.board}/vacancies?")).text,
            base,
            lambda h: urlsplit(h).path.startswith(PREFIX) and len(urlsplit(h).path) > len(PREFIX),
        )
        if not urls:  # a handful of roles at a time, but never none: the markup moved
            raise ValueError("jettycloud: the listing links no vacancies, the markup changed?")

        async def build(url: str) -> JobStub | None:
            page = await page_text(http, url)
            v = vacancy(page, _slug(url)) if page else None
            if not v or not v.get("id") or not v.get("name"):
                return None
            link = base + (v.get("slug") or _slug(url))
            return JobStub(
                source=self.name,
                url=link,
                title=" ".join(str(v["name"]).split()),
                company="JettyCloud",
                description=strip_html(editor_html(v.get("content") or "")),
                ats=self.name,  # the site has no structured location: left empty
                apply_url=link,
                extra={"id": str(v["id"])},
            )

        async for stubs in hydrate(urls, start_page, build, CHUNK):
            yield stubs
