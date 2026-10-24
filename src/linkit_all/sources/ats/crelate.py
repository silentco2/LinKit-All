"""Crelate candidate portals (jobs.crelate.com/portal/<slug>) through their keyless public API.
Logic adapted from freehire (MIT)."""

import json
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f12 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://jobs.crelate.com/api/candidateportal/GetAllJobs"


class Crelate(Source):
    """The board is `<portalSlug>/<organizationId>`: the slug builds the job URLs, the
    OrganizationId GUID (embedded in the portal page) keys the API. `crelate:slug/GUID` works;
    a portal URL alone cannot be detected because it does not carry the GUID. A portal often
    fronts a staffing network, so each job's employer is the posting's CompanyName."""

    name = "crelate"
    kind = "ats"
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one call returns every posting
            return
        slug, _, org = task.board.partition("/")
        if not slug or not org:
            raise ValueError(
                f"crelate board {task.board!r} must be '<portalSlug>/<organizationId>'"
            )
        envelope = {"Locations": None, "OrganizationId": org, "SearchText": None, "Tags": None}
        data = await http.get_json(API, params={"requestEnvelope": json.dumps(envelope)})
        if data.get("IsError"):
            raise ValueError(f"crelate: {task.board}: portal error: {data.get('ErrorMessage')}")
        yield [self.stub(j, slug, task.board) for j in data.get("Jobs") or [] if j.get("Id")]

    @staticmethod
    def stub(j: dict[str, Any], slug: str, board: str) -> JobStub:
        code = j.get("JobCode") or (j.get("Url") or "").lstrip("/")
        url = f"https://jobs.crelate.com/portal/{slug}/job/{code}"
        place = [str(j.get(k) or "").strip() for k in ("City", "State")]
        location = ", ".join(p for p in place if p) or str(j.get("Country") or "").strip()
        return JobStub(
            source="crelate",
            url=url,
            title=(j.get("Title") or "").strip(),
            company=(j.get("CompanyName") or "").strip() or name_from_slug(slug),
            location=location,
            description=html_to_text(j.get("Description") or ""),
            posted_at=from_iso(j.get("LastPostedOnDate")),
            ats="crelate",
            apply_url=url,
            remote=remote_from_text(location, j.get("Title")),
            extra={"board": board, "id": j["Id"]},
        )
