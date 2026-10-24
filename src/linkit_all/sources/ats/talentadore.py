"""TalentAdore Hire (Nordic ATS): the board is the employer's feed token, the data-url token its
career widget reads from ats.talentadore.com/positions/<token>/json. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.sources.ats._f16 import when
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http


class TalentAdore(Source):
    name = "talentadore"
    kind = "ats"
    url_patterns = (re.compile(r"ats\.talentadore\.com/positions/(\w+)", re.I),)
    cdx_hosts = ("ats.talentadore.com/positions/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one request lists the whole board
            return
        # v=2 makes the feed write RFC 3339 dates; without it they carry no time zone
        feed = await http.get_json(f"https://ats.talentadore.com/positions/{task.board}/json?v=2")
        company = " ".join(str(feed.get("company") or "").split()) or task.board
        stubs = []
        for job in feed.get("jobs") or []:
            token = str(job.get("job_token") or "").strip()
            url = str(job.get("link") or "").strip()
            title = " ".join(str(job.get("name") or "").split())
            if not (token and url and title):
                continue
            # city/county/country make the location; `location` is a street address
            parts = (str(job.get(k) or "").strip() for k in ("city", "county", "country"))
            location = ", ".join(p for p in parts if p)
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url,
                    title=title,
                    company=company,
                    location=location,
                    description=strip_html(job.get("description_html") or "")
                    or strip_html(job.get("description_text") or ""),
                    posted_at=when(job.get("start_date")) or when(job.get("updated")),
                    ats=self.name,
                    apply_url=url,
                    remote=remote_from_text(location),
                    extra={"board": task.board, "id": token},
                )
            )
        yield stubs
