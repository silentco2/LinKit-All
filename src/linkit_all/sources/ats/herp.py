"""HERP career pages (herp.careers/v1/{board}): a server-rendered listing (optionally one level
of requisition groups) and a schema.org JobPosting on each job page. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator, Callable
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.parsing import name_from_slug

CHUNK = 20  # job pages fetched per yielded page
# Single segments under /v1/<board>/ that are the platform's own pages, never a job id.
_NOT_JOBS = frozenset({"top"})


def _tail(board: str, href: str) -> str:
    """The path after /v1/<board>/ when `href` is a herp.careers URL of exactly this board."""
    parts = urlsplit(href)
    prefix = f"/v1/{board}/"
    # Matched by host and path, never by substring: a share widget's query may embed a real URL.
    if (parts.netloc and parts.netloc != "herp.careers") or not parts.path.startswith(prefix):
        return ""
    return parts.path.removeprefix(prefix)


def _is_job(tail: str) -> bool:
    return bool(tail) and "/" not in tail and tail not in _NOT_JOBS


def _is_group(tail: str) -> bool:
    return tail.startswith("requisition-groups/")


class Herp(Source):
    """The board is the company's slug: `a244` for herp.careers/v1/a244."""

    name = "herp"
    kind = "ats"
    url_patterns = (re.compile(r"herp\.careers/v1/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board
        links = await self._links(http, board)
        for i in range(start_page * CHUNK, len(links), CHUNK):
            posts = [await self.posting(http, u, board) for u in links[i : i + CHUNK]]
            yield [p for p in posts if p]

    @staticmethod
    async def _links(http: Http, board: str) -> list[str]:
        base = f"https://herp.careers/v1/{board}"
        root = (await get_page(http, base)).text

        def anchors(html: str, keep: Callable[[str], bool]) -> list[str]:
            out = []
            for a in LexborHTMLParser(html).css("a[href]"):
                href = urljoin(base + "/", a.attributes["href"] or "").split("#")[0]
                if keep(_tail(board, href)) and href not in out:
                    out.append(href)
            return out

        jobs = anchors(root, _is_job)
        for group in anchors(root, _is_group):  # one level deep, like the site
            for link in anchors((await get_page(http, group)).text, _is_job):
                if link not in jobs:
                    jobs.append(link)
        return jobs

    async def posting(self, http: Http, url: str, board: str) -> JobStub | None:
        await http.allowed(url)
        resp = await http.get(url)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
        found = job_postings(resp.text)[:1]
        if not found or not found[0].get("title"):
            return None
        stub = to_stub(found[0], "herp", url, "herp")
        company = name_from_slug(board) if stub.company == "Unknown" else stub.company
        return stub.model_copy(
            update={
                "company": company,
                "remote": stub.remote or remote_from_text(stub.location),
                "extra": {**stub.extra, "board": board, "id": url.rstrip("/").rsplit("/", 1)[-1]},
            }
        )
