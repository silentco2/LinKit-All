"""Jibe career sites (the career-site product fronting iCIMS, e.g. www.github.careers): a paged
JSON listing at /api/jobs whose entries already hold the full posting HTML. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import mode, name_from_host
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

PAGE_SIZE = 100
MAX_PAGES = 500
LIST = "https://{board}/api/jobs?page={page}&limit=" + str(PAGE_SIZE)
JOB = "https://{board}/careers-home/jobs/{id}"


class Jibe(Source):
    """The board is the career site's public host: `www.github.careers`."""

    name = "jibe"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])([\w-]+(?:\.[\w-]+)+)/careers-home/jobs/[\w-]+", re.I),)
    parallel = 2  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board, got = task.board, start_page * PAGE_SIZE
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(LIST.format(board=board, page=page))
            rows = data.get("jobs") or []
            if not rows:
                return
            yield [s for r in rows if (s := self.stub(r.get("data") or {}, board))]
            got += len(rows)
            if got >= (data.get("totalCount") or 0):
                return

    def stub(self, p: dict[str, Any], board: str) -> JobStub | None:
        job_id = p.get("slug") or p.get("req_id")
        if not job_id:  # no id: every such posting would share one bare URL
            return None
        url = JOB.format(board=board, id=job_id)
        where = p.get("location_name") or p.get("full_location") or ""
        return JobStub(
            source=self.name,
            url=url,
            title=(p.get("title") or "").strip(),
            company=p.get("hiring_organization") or name_from_host(board),
            location=where,
            description=html_to_text(p.get("description") or ""),
            posted_at=from_iso(p.get("posted_date")),  # "2026-06-16T20:41:00+0000"
            ats=self.name,
            apply_url=url,
            remote=mode(p.get("location_type")) or remote_from_text(where),
            extra={"board": board, "id": str(job_id)},
        )
