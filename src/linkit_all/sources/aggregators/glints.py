"""Glints (glints.com), jobs in Indonesia, Singapore, Malaysia and Vietnam, through the keyless
GraphQL endpoint its own search page calls (with that page's Origin and Referer). One task per
search query; Indonesia unless the task names a country. The list has no body.
Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date
from linkit_all.sources.tasks import limited, query_tasks

API = "https://glints.com/api/v2-alc/graphql"
JOB = "https://glints.com/id/opportunities/jobs/{}"
PAGE = 30
MAX_PAGES = 10
QUERY = """query searchJobsV3($data: JobSearchConditionInput!) {
  searchJobsV3(data: $data) {
    jobsInPage {
      id
      title
      company { name brandName }
      city { name }
      country { code name }
      createdAt
    }
    hasMore
  }
}"""
HEADERS = {
    "Origin": "https://glints.com",
    "Referer": "https://glints.com/id/opportunities/jobs/explore",
}


class Glints(Source):
    name = "glints"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        country = (task.country or "ID").upper()
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = {
                "SearchTerm": task.query,
                "CountryCode": country,
                "includeExternalJobs": True,
                "pageSize": PAGE,
                "page": page,
            }
            body = {"operationName": "searchJobsV3", "query": QUERY, "variables": {"data": data}}
            got = await http.post_json(API, body, headers=HEADERS)
            if not isinstance(got, dict) or got.get("errors"):
                raise ValueError("glints: the API answered with errors (schema changed?)")
            found = (got.get("data") or {}).get("searchJobsV3") or {}
            rows = found.get("jobsInPage")
            if not isinstance(rows, list):
                raise ValueError("glints: the response carries no jobsInPage array")
            yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            if len(rows) < PAGE or found.get("hasMore") is False:
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        jid, title = str(r.get("id") or "").strip(), clean(r.get("title"))
        org = r.get("company") or {}
        company = clean(org.get("name") or org.get("brandName"))
        if not (jid and title and company):
            return None
        place = ", ".join(
            x
            for x in (
                clean((r.get("city") or {}).get("name")),
                clean((r.get("country") or {}).get("name")),
            )
            if x
        )
        url = JOB.format(quote(jid, safe=""))
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=place,
            posted_at=safe_date(r.get("createdAt")),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(place, title),
            extra={"id": jid},
        )
