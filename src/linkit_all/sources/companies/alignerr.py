"""Alignerr (www.alignerr.com), an AI-training contractor marketplace: the /jobs page and each
posting page are Next.js pages with the data in __NEXT_DATA__. Single-company plugin; links are
unattributed (no referral code). Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import hydrate, page_text, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ats_of, first, next_data, when

LIST = "https://www.alignerr.com/jobs"
JOB = "https://www.alignerr.com/jobs/"
CHUNK = 20  # posting pages read together per page of stubs


def _page_props(html: str | None) -> dict[str, Any]:
    props = ((next_data(html) or {}).get("props") or {}).get("pageProps") if html else None
    return props if isinstance(props, dict) else {}


class Alignerr(Source):
    name = "alignerr"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "alignerr:jobs")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        listed = _page_props(await page_text(http, LIST)).get("initialJobs") or []
        items = [x for x in listed if isinstance(x, dict) and x.get("id")]

        async def build(item: dict[str, Any]) -> JobStub | None:
            return await self.posting(http, str(item["id"]).strip(), item)

        async for page in hydrate(items, start_page, build, CHUNK):
            yield page

    async def posting(self, http: Http, pid: str, listed: dict[str, Any]) -> JobStub | None:
        job = _page_props(await page_text(http, JOB + pid)).get("job")
        if not isinstance(job, dict) or not job.get("isActive"):
            return None  # gone, unreadable or closed
        title = first(job, "name") or first(listed, "title")
        if not title:
            return None
        # the listing shows every posting as "Remote"; the posting's own location is the fallback
        location = first(listed, "location") or first(job, "location")
        url = JOB + pid
        return JobStub(
            source=self.name,
            url=url,
            title=" ".join(title.split()),
            company="Alignerr",
            location=location,
            description=strip_html(first(job, "htmlLongDescription", "shortDescription")),
            posted_at=when(first(job, "firstPostDate", "createdAt")),
            ats=ats_of(url, self.name),
            apply_url=url,
            remote=remote_from_text(location),
            extra={"id": pid},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        full = (
            None if stub.description else await self.posting(http, stub.url.rsplit("/", 1)[-1], {})
        )
        return stub.model_copy(update={"description": full.description}) if full else stub
