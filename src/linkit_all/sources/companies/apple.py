"""Apple's careers search (jobs.apple.com/api/v1): a keyless JSON API, 20 postings per page, with
the role text in a per-posting detail call. Single-company plugin. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import paged
from linkit_all.sources.companies._f41 import ats_of, fresh, limited, query_tasks
from linkit_all.sources.http import Http

LOCALE = "en-us"
SEARCH = "https://jobs.apple.com/api/v1/search"
DETAIL = "https://jobs.apple.com/api/v1/jobDetails/{id}?locale=" + LOCALE
JOB = "https://jobs.apple.com/" + LOCALE + "/details/{id}/{slug}"
PAGE = 20  # fixed by the server: a larger request is ignored
_ID = re.compile(r"/details/([^/?#]+)")


def describe(res: dict[str, Any]) -> str:
    """Summary and description as paragraphs, the qualifications as bulleted sections."""
    parts = [str(res.get(k) or "").strip() for k in ("jobSummary", "description")]
    for title, key in (
        ("Minimum Qualifications", "minimumQualifications"),
        ("Preferred Qualifications", "preferredQualifications"),
    ):
        lines = [x.strip() for x in str(res.get(key) or "").splitlines() if x.strip()]
        if lines:
            parts.append(title + "\n" + "\n".join(f"- {x}" for x in lines))
    return "\n\n".join(p for p in parts if p)


class Apple(Source):
    name = "apple"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()  # a multi-location role is listed once per location

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            body = {  # "filters" must be present, even empty: the API rejects the body otherwise
                "query": task.query,
                "filters": {},
                "page": offset // PAGE + 1,
                "locale": LOCALE,
                "sort": "newest",
            }
            res = (await http.post_json(SEARCH, body)).get("res") or {}
            return res.get("searchResults") or [], res.get("totalRecords")

        async def stubs() -> AsyncIterator[list[JobStub]]:
            async for rows in paged(fetch, PAGE, start_page):
                page = fresh((self.stub(r) for r in rows), seen)
                yield page

        async for page in limited(stubs(), task.limit):
            yield page

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        pid, title = str(p.get("positionId") or ""), " ".join(str(p.get("postingTitle")).split())
        if not pid or not title:
            return None
        url = JOB.format(id=pid, slug=p.get("transformedPostingTitle") or "")
        places = [str(x.get("name") or "").strip() for x in p.get("locations") or []]
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Apple",
            location="; ".join(x for x in places if x),
            posted_at=from_iso(p.get("postDateInGMT")),
            ats=ats_of(url, self.name),
            apply_url=url,
            remote="remote" if p.get("homeOffice") else None,
            extra={"id": pid},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if stub.description or not m:
            return stub
        res = (await http.get_json(DETAIL.format(id=m[1]))).get("res") or {}
        return stub.model_copy(update={"description": describe(res)})
