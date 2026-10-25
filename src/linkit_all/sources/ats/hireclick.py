"""HireClick career sites ({board}.hireclick.com): the board page names the organisation, a JSON
endpoint lists its postings, and each posting page carries a schema.org JobPosting. Logic
adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

BOARD = "https://{board}.hireclick.com/jobboard/jobboard.aspx"
LIST = "https://{board}.hireclick.com/api/Controllers/JobBoard/GetSettingsAndJobs?orgGUID={guid}"
_ID = re.compile(r"//([\w-]+)\.hireclick\.com/jb/[^/]+/view/(\d+)", re.I)


def _posted(value: str | None) -> datetime | None:
    """The US-locale, zone-less "9/16/2026 10:58:32 AM"."""
    try:
        return datetime.strptime((value or "").strip(), "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        return None


class HireClick(Source):
    """The board is the tenant subdomain: `williamsnd` for williamsnd.hireclick.com. The pages
    are heavy and slow (1-3 MB each), so the listing carries no description and `fetch_details`
    reads the posting page only for jobs that get that far."""

    name = "hireclick"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!www\.)([\w-]+)\.hireclick\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        board = task.board.lower()
        page = LexborHTMLParser((await get_page(http, BOARD.format(board=board))).text)
        guid_input = page.css_first("input#hdnOrgGuid")
        guid = (guid_input.attributes["value"] or "").strip() if guid_input else ""
        if not guid:  # an unknown tenant redirects to a maintenance page
            raise ValueError(
                f"hireclick: no organisation id on the {board} board page (no such tenant)"
            )
        # The endpoint answers a JSON *string* holding the JSON document.
        raw = (await get_page(http, LIST.format(board=board, guid=quote(guid)))).json()
        doc = json.loads(raw) if isinstance(raw, str) else raw
        seen: set[str] = set()
        stubs = []
        for j in doc.get("JobList") or []:
            m = _ID.search(j.get("JobURL") or "")
            if not m or m[2] in seen:
                continue
            seen.add(m[2])
            city = (j.get("JobCity") or "").strip()
            stubs.append(
                JobStub(
                    source="hireclick",
                    url=j["JobURL"],
                    title=" ".join((j.get("JobTitle") or "").split()),
                    company=name_from_slug(board),
                    location=city,
                    ats="hireclick",
                    apply_url=j["JobURL"],
                    remote=remote_from_text(city),
                    extra={"board": board, "id": m[2], "category": j.get("JobType")},
                )
            )
        yield stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _ID.search(stub.url):
            return stub
        await http.allowed(stub.url)
        resp = await http.get(stub.url)
        # A taken-down posting redirects to /jobboard/ instead of answering 404.
        if resp.status_code in (404, 410) or resp.is_redirect or not _ID.search(str(resp.url)):
            return stub
        resp.raise_for_status()
        found = job_postings(resp.text)[:1]
        if not found:
            return stub
        p = found[0]
        addr = (p.get("jobLocation") or {}).get("address") or {}
        place = (addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry"))
        # Trimmed part by part: the locality arrives padded ("WILLISTON ") on some tenants.
        location = ", ".join(x.strip() for x in place if isinstance(x, str) and x.strip())
        update = {
            "description": html_to_text(p.get("description") or ""),
            "location": location or stub.location,
            "posted_at": _posted(p.get("datePosted")) or stub.posted_at,
        }
        return stub.model_copy(update=update)
