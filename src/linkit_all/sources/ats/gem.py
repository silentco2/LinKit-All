"""Gem (jobs.gem.com): public job-board GraphQL; the list carries no body, so each posting's
description is a second call. Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import mode, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://jobs.gem.com/api/public/graphql"
CHUNK = 20  # postings per page: their detail calls run together (Http paces them per host)
LIST = """query JobBoardList($boardId: String!) {
  oatsExternalJobPostings(boardId: $boardId) {
    jobPostings { extId title locations { city isoCountry isRemote } job { locationType } }
  }
}"""
DETAIL = """query ExternalJobPostingQuery($boardId: String!, $extId: String!) {
  oatsExternalJobPosting(boardId: $boardId, extId: $extId) { descriptionHtml firstPublishedTsSec }
}"""
_URL = re.compile(r"jobs\.gem\.com/([\w-]+)/([\w-]+)")


async def _query(http: Http, op: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    body = {"operationName": op, "query": query, "variables": variables}
    data = await http.post_json(API, body)
    if data.get("errors"):  # GraphQL answers 200 even when it fails
        raise ValueError(f"gem: {op}: {data['errors'][0].get('message')}")
    return data.get("data") or {}


class Gem(Source):
    """The board is the vanity path: `jobs.gem.com/<board>`."""

    name = "gem"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.gem\.com/([\w-]+)", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        data = await _query(http, "JobBoardList", LIST, {"boardId": task.board})
        postings = (data.get("oatsExternalJobPostings") or {}).get("jobPostings") or []
        postings = [p for p in postings if p.get("extId") and p.get("title")]
        for i in range(start_page * CHUNK, len(postings), CHUNK):
            chunk = postings[i : i + CHUNK]
            details = await asyncio.gather(*(self._detail(http, task.board, p) for p in chunk))
            yield [self.stub(p, task.board, d) for p, d in zip(chunk, details, strict=True)]

    @staticmethod
    async def _detail(http: Http, board: str, p: dict[str, Any]) -> dict[str, Any]:
        try:
            data = await _query(
                http, "ExternalJobPostingQuery", DETAIL, {"boardId": board, "extId": p["extId"]}
            )
        except ValueError:  # one gone posting: keep it, the enrich stage fetches the text again
            return {}
        return data.get("oatsExternalJobPosting") or {}

    @staticmethod
    def stub(p: dict[str, Any], board: str, detail: dict[str, Any]) -> JobStub:
        loc = (p.get("locations") or [{}])[0]
        place = ", ".join(x for x in (loc.get("city"), loc.get("isoCountry")) if x)
        kind = ((p.get("job") or {}).get("locationType") or "").replace("IN_OFFICE", "office")
        url = f"https://jobs.gem.com/{board}/{p['extId']}"
        ts = detail.get("firstPublishedTsSec")
        return JobStub(
            source="gem",
            url=url,
            title=p["title"].strip(),
            company=name_from_slug(board),
            location=place,
            description=strip_html(detail.get("descriptionHtml") or ""),
            posted_at=from_epoch_ms(ts * 1000) if ts else None,
            ats="gem",
            apply_url=url,
            remote="remote" if loc.get("isRemote") else (mode(kind) or remote_from_text(place)),
            extra={"board": board, "id": p["extId"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        data = await _query(
            http, "ExternalJobPostingQuery", DETAIL, {"boardId": m[1], "extId": m[2]}
        )
        text = strip_html((data.get("oatsExternalJobPosting") or {}).get("descriptionHtml") or "")
        return stub.model_copy(update={"description": text}) if text else stub
