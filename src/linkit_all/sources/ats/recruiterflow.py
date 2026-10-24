"""RecruiterFlow agency career pages (recruiterflow.com/<board>/jobs): the whole board is embedded
in the page as `window.jobsList`, each posting's page holds the description. Logic adapted from
freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import get_page, mode, name_from_slug
from linkit_all.sources.ats._f16 import when
from linkit_all.sources.ats.deel import bracket_slice
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.text import html_to_text

LIST = "https://recruiterflow.com/{board}/jobs"
JOB_URL = "https://recruiterflow.com/{board}/jobs/{id}"
_URL = re.compile(r"recruiterflow\.com/([\w-]+)/jobs/(\d+)", re.I)


class RecruiterFlow(Source):
    """A board is a recruiting agency; the company shown is the agency itself."""

    name = "recruiterflow"
    kind = "ats"
    url_patterns = (re.compile(r"recruiterflow\.com/([\w-]+)/jobs", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # no paging: one page holds the board
            return
        page = (await get_page(http, LIST.format(board=task.board))).text
        raw = bracket_slice(page, "window.jobsList = ", "{", "}")
        if raw is None:
            raise ValueError(f"recruiterflow: no window.jobsList on the {task.board} page")
        # department is a list of [name, [postings]] pairs; flatten it.
        groups = json.loads(raw).get("department") or []
        company = name_from_slug(task.board)
        yield [
            self.stub(j, task.board, company) for _, jobs in groups for j in jobs if j.get("job_id")
        ]

    @staticmethod
    def stub(j: dict[str, Any], board: str, company: str) -> JobStub:
        url = JOB_URL.format(board=board, id=j["job_id"])
        where = j.get("details") or ""
        return JobStub(
            source="recruiterflow",
            url=url,
            title=(j.get("job_name") or "").strip(),
            company=company,
            location=where,
            posted_at=when(j.get("last_opened")),
            ats="recruiterflow",
            apply_url=url,
            remote=mode(j.get("remote_type")) or remote_from_text(j.get("job_name"), where),
            extra={"board": board, "id": str(j["job_id"]), "employment": j.get("employment_type")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _URL.search(stub.url):
            return stub
        found = job_postings((await get_page(http, stub.url)).text)[:1]
        if not found:
            return stub
        return stub.model_copy(
            update={"description": html_to_text(found[0].get("description") or "")}
        )
