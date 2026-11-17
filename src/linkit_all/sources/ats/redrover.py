"""Red Rover K12, school-district job boards (jobs.redroverk12.com/org/{board}; the board is the
numeric org id). The page's own public GraphQL API answers up to 500 postings in one call and
has no cursor, so a larger board fails loudly instead of being cut. Internal-only and closed
postings are left out. The list has no body. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date

API = "https://api.redroverk12.com/graphql"
ORIGIN = "https://jobs.redroverk12.com"
QUERY = """query GetJobPostings($search: JobPostingSearchInput!) {
  jobSeekerSiteUnauthenticated {
    jobPostingSearch(search: $search) {
      results {
        id
        name
        organizationName
        location { name }
        activePublicOnDateUtc
        closedOnDateUtc
        allowsRemote
      }
      hasMoreData
    }
  }
}"""


class RedRover(Source):
    name = "redrover"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.redroverk12\.com/org/(\d+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds the whole board
            return
        search = {
            "orgId": task.board,
            "searchTerm": "",
            "locationIds": [],
            "jobPostingCategoryIds": [],
        }
        body = {"operationName": "GetJobPostings", "variables": {"search": search}, "query": QUERY}
        data = await http.post_json(API, body, headers={"Origin": ORIGIN})
        if not isinstance(data, dict) or data.get("errors"):
            raise ValueError("redrover: the API answered with errors")
        found = ((data.get("data") or {}).get("jobSeekerSiteUnauthenticated") or {}).get(
            "jobPostingSearch"
        )
        if not isinstance(found, dict) or not isinstance(found.get("results"), list):
            raise ValueError("redrover: the response carries no results array")
        if found.get("hasMoreData"):
            raise ValueError("redrover: the board has more than 500 postings (no way to page)")
        stubs = [
            s for r in found["results"] if isinstance(r, dict) and (s := self.stub(r, task.board))
        ]
        if stubs:
            yield stubs

    @staticmethod
    def stub(r: dict[str, Any], board: str) -> JobStub | None:
        jid, title = str(r.get("id") or "").strip(), clean(r.get("name"))
        if not (jid and title) or not r.get("activePublicOnDateUtc") or r.get("closedOnDateUtc"):
            return None
        org = clean(r.get("organizationName"))
        url = f"{ORIGIN}/org/{board}/opening/{jid}"
        return JobStub(
            source="redrover",
            url=url,
            title=title,
            company=org or f"Org {board}",
            location=clean((r.get("location") or {}).get("name")),
            posted_at=safe_date(r["activePublicOnDateUtc"]),
            ats="redrover",
            apply_url=url,
            remote="remote" if r.get("allowsRemote") else None,
            extra={"board": board, "id": jid},
        )
