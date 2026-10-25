"""EPAM Systems careers (careers.epam.com): the sitemap lists every vacancy and each vacancy page
carries a JobPosting block plus structured sections. A single-company plugin, not an ATS. Logic
adapted from freehire (MIT)."""

import gzip
import json
import re
from collections.abc import AsyncIterator
from html import escape
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import fetch_all, get_page, sitemap_locs, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

HOST = "careers.epam.com"
CHUNK = 20  # vacancy pages read together per page of stubs
# English vacancy pages only: /uk/, /de/ ... are translations of the same posting.
_URL = re.compile(r"/en/vacancy/[^/?#]*-(blt[a-z0-9]+)_en(?:[/?#]|$)")
_LABELS = {"responsibilities", "requirements", "nice to have", "benefits"}


def _section(title: str, items: list[str]) -> str:
    lis = [i.strip() for i in items if i.strip() and i.strip().lower() not in _LABELS]
    return (
        f"<h3>{title}</h3><ul>{''.join(f'<li>{escape(i)}</li>' for i in lis)}</ul>" if lis else ""
    )


def _next_job(html: str) -> dict[str, Any]:
    node = LexborHTMLParser(html).css_first("script#__NEXT_DATA__")
    try:
        job = json.loads(node.text(deep=True))["props"]["pageProps"]["job"] if node else {}
    except (ValueError, KeyError, TypeError):
        return {}
    return job if isinstance(job, dict) else {}


def parse_vacancy(html: str, url: str) -> JobStub | None:
    m = _URL.search(url)
    postings = job_postings(html)
    if not m or not postings:
        return None
    p, job = postings[0], _next_job(html)
    # The JobPosting description is one flat blob; the page data keeps the sections apart.
    cat = job.get("category") or {}
    parts = [job.get("description") or ""]
    for title, key in (
        ("Responsibilities", "responsibilities"),
        ("Requirements", "requirements"),
        ("Nice to have", "nice_to_have"),
    ):
        parts.append(_section(title, cat.get(key) or []))
    benefits = "".join(b.get("content") or "" for b in job.get("benefits") or [])
    parts.append(f"<h3>Benefits</h3>{benefits}" if benefits.strip() else "")
    description = strip_html("".join(parts)) or strip_html(p.get("description") or "", escaped=True)
    cities = [
        ", ".join(x for x in (c.get("name"), (c.get("country") or {}).get("name")) if x)
        for c in job.get("city") or []
        if isinstance(c, dict)
    ]
    countries = [c.get("name") for c in p.get("applicantLocationRequirements") or []]
    location = "; ".join(dict.fromkeys(c for c in cities if c)) or ", ".join(
        c for c in countries if c
    )
    return JobStub(
        source="epam",
        url=url,
        title=" ".join(str(p.get("title") or "").split()),
        company="EPAM Systems",
        location=location,
        description=description,
        posted_at=from_iso(p.get("datePosted")) if p.get("datePosted") else None,
        apply_url=url,
        remote="remote"
        if p.get("jobLocationType") == "TELECOMMUTE"
        else remote_from_text(location),
        extra={"id": m[1]},
    )


class Epam(Source):
    name = "epam"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "epam:careers", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        resp = await get_page(http, f"https://{HOST}/sitemap.xml.gz")
        raw = resp.content
        xml = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8", "replace")
        urls = sorted({u for u in sitemap_locs(xml) if _URL.search(u)})
        for i in range(start_page * CHUNK, len(urls), CHUNK):
            stubs = await fetch_all(http, urls[i : i + CHUNK], parse_vacancy)
            yield [s for s in stubs if s.title]

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        full = parse_vacancy((await get_page(http, stub.url)).text, stub.url)
        return stub.model_copy(update={"description": full.description}) if full else stub
