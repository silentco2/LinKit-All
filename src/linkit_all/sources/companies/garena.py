"""Garena's careers site (careers.garena.com): a Nuxt app over a keyless JSON API. One POST lists
the whole catalogue; the listing's summary is often empty, so `fetch_details` reads each posting
for its description and requirements. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

HOST = "careers.garena.com"
LIST = "https://{host}/api/job/list?office=global"
DETAIL = "https://{host}/api/job/detail/{id}?office=global"
JOB = "https://{host}/global/careers/{id}"
_ID = re.compile(r"/careers/([^/?#]+)")


class Garena(Source):
    name = "garena"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "garena:careers", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page:  # one unpaged response: nothing after page 0
            return
        data = await http.post_json(LIST.format(host=task.board), {})
        if not isinstance(data.get("jobs"), list):
            raise ValueError("garena: the listing carries no jobs array")
        stubs = [s for it in data["jobs"] if (s := self.stub(it, task.board))]
        if stubs:
            yield stubs

    def stub(self, it: dict[str, Any], host: str) -> JobStub | None:
        jid, title = str(it.get("id") or "").strip(), " ".join((it.get("title") or "").split())
        if not jid or not title:
            return None
        tags = it.get("tags") or {}
        places = [p.strip() for p in tags.get("location") or [] if p and p.strip()]
        remote = any(p.lower() == "remote" for p in places)
        url = JOB.format(host=host, id=quote(jid, safe=""))
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Garena",
            location="; ".join(p for p in places if p.lower() != "remote"),
            ats=self.name,
            apply_url=url,
            remote="remote" if remote else None,
            extra={
                "id": jid,
                "category": tags.get("job_category"),
                "type": tags.get("job_type"),
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not (m := _ID.search(stub.url)):
            return stub
        data = await http.get_json(DETAIL.format(host=HOST, id=m[1]))
        job = data.get("job") or {}  # a posting that is gone answers 200 with an empty object
        # The page's own order: the summary, then "Job Description" and "Job Requirements".
        html = (job.get("description") or "") + "".join(
            f"<h3>{head}</h3>{job[key]}"
            for head, key in (
                ("Job Description", "job_description"),
                ("Job Requirements", "job_requirements"),
            )
            if (job.get(key) or "").strip()
        )
        return stub.model_copy(update={"description": strip_html(html)}) if html else stub
