"""AppOne (Paychex applicant tracking), job portals at jobs.appone.com/<slug>. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import retry_while
from linkit_all.sources.http import Http

PORTAL = "https://jobs.appone.com/api/portal/v1/companyjobposts/{board}"
POSTING = "https://apply.appone.com/api/apply/v2/jobposting/{id}"
JOB_URL = "https://apply.appone.com/job/{id}"
_JOB = re.compile(r"apply\.appone\.com/job/(\w+)", re.I)
_MODES: dict[str, Remote] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


async def get_json(http: Http, url: str) -> Any:
    """GET as JSON. The edge answers a bare 403 (never 429) when it finds a client too fast, and
    now and then at a gentle pace too: wait and ask again before giving up."""
    resp = await retry_while(lambda: http.get(url), attempts=3, base_delay=2.0)
    resp.raise_for_status()
    return resp.json()


def salary(s: dict[str, Any] | None) -> dict[str, Any]:
    """The portal's structured pay. The currency is not stated; AppOne is a Paychex US product."""
    if not s or not s.get("periodType"):
        return {}
    lo, hi = s.get("minimum"), s.get("maximum")
    match s.get("salaryOption"):
        case "RANGE":
            pass
        case "EXACT_AMOUNT":
            hi = lo
        case "STARTING_AMOUNT":
            hi = None
        case "MAXIMUM_AMOUNT":
            lo = None
        case _:
            return {}
    if lo is None and hi is None:
        return {}
    return {
        "salary_min": lo,
        "salary_max": hi,
        "salary_currency": "USD",
        "salary_interval": s["periodType"].lower(),
    }


class AppOne(Source):
    name = "appone"
    kind = "ats"
    url_patterns = (
        re.compile(r"jobs\.appone\.com/api/portal/v1/companyjobposts/([\w-]+)", re.I),
        re.compile(r"jobs\.appone\.com/(?!api/)([\w-]+)", re.I),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        # One unpaginated answer, capped by the platform at the 100 newest postings.
        data = await get_json(http, PORTAL.format(board=task.board))
        company = (data.get("companyName") or task.board).strip()
        yield [
            self.stub(p, company, task.board)
            for p in data.get("jobPosts") or []
            if p.get("jobPostId")
        ]

    @staticmethod
    def stub(p: dict[str, Any], company: str, board: str) -> JobStub:
        url = p.get("jobPostUrl") or JOB_URL.format(id=p["jobPostId"])
        return JobStub(
            source="appone",
            url=url,
            title=(p.get("jobTitle") or "").strip(),
            company=company,
            location=(p.get("location") or "").strip(),
            posted_at=from_iso(p.get("datePosted")),
            ats="appone",
            apply_url=url,
            remote=_MODES.get(re.sub(r"[\s_-]", "", (p.get("workplaceType") or "").lower())),
            extra={"board": board, "id": p["jobPostId"], "employment": p.get("jobType")},
            **salary(p.get("salary")),
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _JOB.search(stub.url)
        if not m:
            return stub
        resp = await retry_while(
            lambda: http.get(POSTING.format(id=m[1])), attempts=3, base_delay=2.0
        )
        if resp.status_code == 404:  # closed or removed
            return stub
        resp.raise_for_status()
        # The body is plain text with newline-separated paragraphs already.
        return stub.model_copy(
            update={"description": (resp.json().get("description") or "").strip()}
        )
