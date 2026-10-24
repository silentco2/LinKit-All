"""Mindsight (oportunidades.mindsight.com.br), a Brazilian ATS: each tenant page is a Next.js app
whose __NEXT_DATA__ lists the postings; the body is on each posting's own page. Logic adapted from
freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.ats._f16 import chunks, next_data, page_text, when
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

HOST = "https://oportunidades.mindsight.com.br"
_WORK_MODEL: dict[str, Remote] = {"REMOTE": "remote", "HYBRID": "hybrid", "IN_PERSON": "onsite"}
_URL = re.compile(r"oportunidades\.mindsight\.com\.br/([\w-]+)/(\d+)")


def _page_props(html: str) -> dict[str, Any]:
    return ((next_data(html) or {}).get("props") or {}).get("pageProps") or {}


async def _description(http: Http, url: str) -> str:
    html = await page_text(http, url)
    posting = _page_props(html).get("jobPosting") if html else None
    return strip_html((posting or {}).get("description") or "")


class Mindsight(Source):
    """The board is the tenant path: `oportunidades.mindsight.com.br/<board>`."""

    name = "mindsight"
    kind = "ats"
    url_patterns = (re.compile(r"oportunidades\.mindsight\.com\.br/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        resp = await get_page(http, f"{HOST}/{task.board}")
        posts = _page_props(resp.text).get("publicJobPostings")
        if not isinstance(posts, list):
            raise ValueError(f"mindsight: no postings in the page of {task.board!r}")
        live = [
            p
            for p in posts
            if p.get("id") and p.get("name") and p.get("status") in (None, "", "IN_PROGRESS")
        ]
        company = name_from_slug(task.board)
        for chunk in chunks(live, start_page):
            urls = [f"{HOST}/{task.board}/{p['id']}" for p in chunk]
            texts = await asyncio.gather(*(_description(http, u) for u in urls))
            yield [
                self.stub(p, u, t, task.board, company)
                for p, u, t in zip(chunk, urls, texts, strict=True)
            ]

    @staticmethod
    def stub(p: dict[str, Any], url: str, text: str, board: str, company: str) -> JobStub:
        place = (p.get(k) for k in ("city", "state", "country"))
        return JobStub(
            source="mindsight",
            url=url,
            title=" ".join(str(p.get("name") or "").split()),
            company=company,
            location=", ".join(x for x in place if x),
            description=text,  # empty when the page could not be read: the enrich stage retries
            posted_at=when(p.get("external_publication_start_at")) or when(p.get("created_at")),
            ats="mindsight",
            apply_url=url,
            remote=_WORK_MODEL.get(str(p.get("work_model") or "").strip().upper()),
            extra={"board": board, "id": str(p["id"])},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        text = (
            ""
            if stub.description or not _URL.search(stub.url)
            else await _description(http, stub.url)
        )
        return stub.model_copy(update={"description": text}) if text else stub
