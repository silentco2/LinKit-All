"""micro1 job board (jobs.micro1.ai): the sitemap lists every posting and each page's Next.js
flight data carries the job record. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import fetch_all, get_page, sitemap_locs
from linkit_all.sources.ats._f16 import chunks
from linkit_all.sources.ats.deel import bracket_slice, decode_flight, text_rows
from linkit_all.sources.base import JobStub, Remote, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.companies._f43 import careers_task
from linkit_all.sources.http import Http

SITEMAP = "https://jobs.micro1.ai/sitemap.xml"
CHUNK = 20  # posting pages read together per page of stubs
_POST = re.compile(
    r"^https?://jobs\.micro1\.ai/post/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/?$"
)
_MODES: dict[str, Remote] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


def parse_post(html: str, url: str) -> JobStub | None:
    try:
        flight = decode_flight(html)
        raw = bracket_slice(flight, '"data":{"client_job_id"', "{", "}")
        d: dict[str, Any] = json.loads(raw) if raw else {}
    except ValueError:
        return None
    title = " ".join(str(d.get("job_role_name") or "").split())
    if not d.get("client_job_id") or not title or d.get("job_status") not in (None, "", "open"):
        return None
    desc = d.get("job_description") or ""
    if desc.startswith("$"):  # a reference to one of the flight's text rows
        desc = text_rows(flight).get(desc[1:], "")
    location = (d.get("location_name") or "").strip()
    try:
        posted = datetime.fromisoformat(d["create_datetime"]) if d.get("create_datetime") else None
    except ValueError:
        posted = None
    url = url.rstrip("/")
    return JobStub(
        source="micro1",
        url=url,
        apply_url=url,
        title=title,
        company="micro1",
        location=location,
        description=strip_html(desc),
        posted_at=posted,
        ats="micro1",
        remote=_MODES.get(str(d.get("location_type") or "").lower())
        or remote_from_text(title, location),
        extra={"micro1_id": d["client_job_id"], "skills": d.get("required_skills") or []},
    )


class Micro1(Source):
    name = "micro1"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        urls = [u for u in sitemap_locs((await get_page(http, SITEMAP)).text) if _POST.match(u)]
        for batch in chunks(urls, start_page, CHUNK):
            yield await fetch_all(http, list(batch), parse_post)
