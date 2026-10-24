"""BeeSite (milch & zucker), the career-site platform behind German corporate job portals
such as Mercedes-Benz and Porsche; the board is the portal's <name>.app.beesite.de host.
Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

PAGE_SIZE = 100
_HOST = re.compile(r"^[a-z0-9][a-z0-9.-]*\.beesite\.de$")


def body_from_page(html: str) -> str:
    """The posting page's description: the schema.org JobPosting (entity-encoded HTML), else the
    template's own description container (postings handled outside the portal have none)."""
    tree = LexborHTMLParser(html)
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text(deep=True)
        # Some tenants print a stray token ("entryLevel [{...}]") before the JSON.
        start = min((i for i in (raw.find("["), raw.find("{")) if i >= 0), default=-1)
        try:
            data = json.loads(raw[start:], strict=False) if start >= 0 else None
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            if text := html_to_text(item.get("description") or "", escaped=True):
                return text
    box = tree.css_first("div.jobad-dynamic-html-container")
    return html_to_text(box.html or "") if box else ""


def place(loc: dict[str, Any]) -> str:
    parts = (loc.get("CityName"), loc.get("CountryName"))
    return ", ".join(p.strip() for p in parts if p and p.strip())


class BeeSite(Source):
    name = "beesite"
    kind = "ats"
    url_patterns = (re.compile(r"https?://([\w.-]+\.beesite\.de)\b", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.strip().lower()
        if not _HOST.match(host):
            raise ValueError(f"beesite board {task.board!r} is not a *.beesite.de host")

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            query = {
                "LanguageCode": "EN",
                "SearchParameters": {"FirstItem": offset + 1, "CountItem": PAGE_SIZE},
            }
            data = await http.get_json(
                f"https://{host}/search", params={"data": json.dumps(query, separators=(",", ":"))}
            )
            result = data.get("SearchResult") or {}
            return result.get("SearchResultItems") or [], result.get("SearchResultCountAll")

        async for items in paged(fetch, PAGE_SIZE, start_page):
            stubs = [
                self.stub(i.get("MatchedObjectDescriptor") or {}, i.get("MatchedObjectId"), host)
                for i in items
            ]
            yield [s for s in stubs if s]

    @staticmethod
    def stub(d: dict[str, Any], job_id: str | None, host: str) -> JobStub | None:
        url = (d.get("PositionURI") or "").strip()
        title = " ".join((d.get("PositionTitle") or "").split())
        if not (job_id and title and url.startswith(("https://", "http://"))):
            return None
        location = "; ".join(
            dict.fromkeys(p for p in map(place, d.get("PositionLocation") or []) if p)
        )
        text = "".join(
            part.get(k) or ""
            for part in d.get("PositionFormattedDescription") or []
            for k in ("Content", "Tasks", "Qualifications")
        )
        return JobStub(
            source="beesite",
            url=url,
            title=title,
            company=(d.get("ParentOrganizationName") or "").strip()
            or host.split(".")[0].split("-")[0].title(),
            location=location,
            description=html_to_text(text),
            posted_at=from_iso(d.get("PublicationStartDate")),
            ats="beesite",
            apply_url=(d.get("ApplyURI") or [url])[0],
            remote=remote_from_text(location),
            extra={"board": host, "id": job_id},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        # The page is on the employer's own domain, not the BeeSite host: check its robots.txt.
        if stub.description or not await http.allowed(stub.url):
            return stub
        resp = await http.get(stub.url)
        resp.raise_for_status()
        return stub.model_copy(update={"description": body_from_page(resp.text)})
