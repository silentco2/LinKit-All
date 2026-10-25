"""Ashby boards whose public posting API is switched off (ashby.py then fails with a 404): Ashby's
own hosted careers widget still answers a keyless embed GraphQL endpoint. It has no compensation,
dates or workplace type, so use it only as the fallback, by naming the board
`ashbygraphql:<slug>`. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import GONE, hydrate
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

URL = "https://jobs.ashbyhq.com/api/non-user-graphql?op={op}"
JOB = "https://jobs.ashbyhq.com/{board}/{id}"
CHUNK = 20  # postings per yielded page: their detail queries run together
LIST_OP = "ApiJobBoardWithTeams"
DETAIL_OP = "ApiJobPosting"
LIST_QUERY = (
    "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) { "
    "jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) "
    "{ jobPostings { id title locationName employmentType } } }"
)
DETAIL_QUERY = (
    "query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { "
    "jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, "
    "jobPostingId: $jobPostingId) { id title descriptionHtml locationName } }"
)


class AshbyGraphQL(Source):
    """The board is the Ashby slug of `jobs.ashbyhq.com/<slug>`. No URL pattern: those URLs belong
    to the ashby plugin, so a board comes here only when named with `ashbygraphql:<slug>`."""

    name = "ashbygraphql"
    kind = "ats"
    parallel = 2  # public JSON endpoint; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board
        listing = await self.query(
            http, LIST_OP, LIST_QUERY, {"organizationHostedJobsPageName": board}
        )
        postings = [
            p for p in ((listing.get("jobBoard") or {}).get("jobPostings") or []) if p.get("id")
        ]

        async def build(p: dict[str, Any]) -> JobStub | None:
            try:
                data = await self.query(
                    http,
                    DETAIL_OP,
                    DETAIL_QUERY,
                    {"organizationHostedJobsPageName": board, "jobPostingId": p["id"]},
                )
            except GONE:
                return None  # one posting's failure never aborts the board
            return self.stub(p, (data.get("jobPosting") or {}).get("descriptionHtml") or "", board)

        async for stubs in hydrate(postings, start_page, build, CHUNK):
            yield stubs

    @staticmethod
    async def query(http: Http, op: str, query: str, variables: dict[str, str]) -> dict[str, Any]:
        body = {"operationName": op, "variables": variables, "query": query}
        data = await http.post_json(URL.format(op=op), body)
        return data.get("data") or {}

    @staticmethod
    def stub(p: dict[str, Any], description: str, board: str) -> JobStub:
        url = JOB.format(board=board, id=p["id"])
        location = p.get("locationName") or ""
        return JobStub(
            source="ashbygraphql",
            url=url,
            title=" ".join((p.get("title") or "").split()),
            company=name_from_slug(board),
            location=location,
            description=html_to_text(description),
            ats="ashby",  # the application is Ashby's, so the Ashby apply handler takes it
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": board, "id": p["id"], "employment": p.get("employmentType")},
        )
