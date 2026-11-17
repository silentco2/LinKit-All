"""Atlassian's careers site (www.atlassian.com/company/careers): one public JSON feed lists every
open posting. Each row has the iCIMS posting page (kept as the address) and the apply form.
The feed's place strings are full of runs of spaces and are tidied. The list has no body: the
posting page's JobPosting data gives it. Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean
from linkit_all.sources.tasks import careers_task
from linkit_all.sources.text import html_to_text

FEED = "https://www.atlassian.com/endpoint/careers/listings"


class Atlassian(Source):
    name = "atlassian"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds the whole board
            return
        rows = await http.get_json(FEED)
        if not isinstance(rows, list):
            raise ValueError("atlassian: the feed is not a list of postings")
        stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
        if stubs:
            yield stubs

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        title = clean(r.get("title"))
        page = str((r.get("portalJobPost") or {}).get("portalUrl") or "").strip()
        apply = str(r.get("applyUrl") or "").strip()
        url = next((u for u in (page, apply) if u.startswith(("https://", "http://"))), "")
        if not (title and url):
            return None
        places = [clean(p) for p in r.get("locations") or [] if isinstance(p, str)]
        where = "; ".join(p for p in places if p)
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Atlassian",
            location=where,
            ats="icims",
            apply_url=apply or url,
            remote=remote_from_text(where),
            extra={"id": str(r.get("id") or url), "category": r.get("category")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
