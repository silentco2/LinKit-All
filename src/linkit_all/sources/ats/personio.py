"""Personio career sites (<tenant>.jobs.personio.com): the public XML feed lists every open position
with its body inline. Logic adapted from freehire (MIT)."""

import asyncio
import html
import re
from collections.abc import AsyncIterator

import httpx
from lxml import etree

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import page_text
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import name_from_slug, when
from linkit_all.sources.text import html_to_text

DOMAINS = ("com", "de")  # a tenant is served from one of them
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def body_of(position: etree._Element) -> str:
    """The position's jobDescription values (HTML, several per position) as plain text."""
    values = (v.text or "" for v in position.iterfind("jobDescriptions/jobDescription/value"))
    return html_to_text("".join(values))


class Personio(Source):
    """The board is the tenant: `acme` for acme.jobs.personio.com (or .de)."""

    name = "personio"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])([\w-]+)\.jobs\.personio\.(?:com|de)\b", re.I),)
    cdx_hosts = ("*.jobs.personio.com", "*.jobs.personio.de")
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is one document
            return
        board = task.board.strip().lower()
        if not re.fullmatch(r"[\w-]+", board):
            raise ValueError(f"personio: board {task.board!r} is not a tenant")
        host, positions = await self.feed(http, board)
        # The default feed is locale-gated: a position published only in another locale has an
        # empty body there. The English feed, fetched once and only when needed, fills the gaps.
        english: dict[str, str] = {}
        if any(not body_of(p) for p in positions):
            try:
                _, more = await self.feed(http, board, host, "en")
                english = {p.findtext("id") or "": body_of(p) for p in more}
            except (httpx.HTTPError, RetryableStatus, etree.XMLSyntaxError, ValueError):
                pass  # best effort: only the body is at stake, not the position
        company = name_from_slug(board)
        stubs = await asyncio.gather(
            *(self.stub(http, p, host, board, company, english) for p in positions)
        )
        yield [s for s in stubs if s is not None]

    @staticmethod
    async def feed(
        http: Http, board: str, host: str | None = None, lang: str = ""
    ) -> tuple[str, list[etree._Element]]:
        """(host, positions) of the tenant's XML feed; with no `host` each domain is tried."""
        query = f"?language={lang}" if lang else ""
        for domain in [host] if host else [f"{board}.jobs.personio.{d}" for d in DOMAINS]:
            resp = await http.get(f"https://{domain}/xml{query}")
            if resp.status_code == 404 and not host:
                continue
            resp.raise_for_status()
            root = etree.fromstring(resp.content, _PARSER)
            return domain, list(root.iterfind("position"))
        raise ValueError(f"personio: no feed for tenant {board!r}")

    @staticmethod
    async def stub(
        http: Http,
        p: etree._Element,
        host: str,
        board: str,
        company: str,
        english: dict[str, str],
    ) -> JobStub | None:
        ident = (p.findtext("id") or "").strip()
        title = " ".join((p.findtext("name") or "").split())
        if not ident or not title:
            return None
        url = f"https://{host}/job/{ident}"
        description = body_of(p) or english.get(ident, "")
        if not description:  # some tenants render the body as a JobPosting on the position page
            page = await page_text(http, url)
            found = job_postings(page) if page else []
            description = (
                html_to_text(html.unescape(str(found[0].get("description") or ""))) if found else ""
            )
        office = (p.findtext("office") or "").strip()
        created = (p.findtext("createdAt") or "").strip()
        return JobStub(
            source="personio",
            url=url,
            title=title,
            company=company,
            location=office,
            description=description,
            posted_at=when(created),
            ats="personio",
            apply_url=url,
            remote=remote_from_text(office),  # the feed has no remote flag
            extra={"board": board, "id": ident, "department": p.findtext("department")},
        )
