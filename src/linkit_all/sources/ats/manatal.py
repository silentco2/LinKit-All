"""Manatal career pages (the ATS behind careers-page.com): a keyless, DRF-paged JSON list carries
every posting with its HTML body. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug

LIST = "https://open.api.manatal.com/open/v3/career-page/{slug}/jobs/"
MAX_PAGES = 200  # the biggest boards are about ten pages; a feed that never ends must not loop


class Manatal(Source):
    """The board is the career-page slug: `careers-page.com/<slug>`."""

    name = "manatal"
    kind = "ats"
    url_patterns = (re.compile(r"careers-page\.com/([\w-]+)", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slug = quote(task.board, safe="")
        base = LIST.format(slug=slug)
        # DRF pages by ?page=N; the "next" link keeps the walk honest, the number resumes it.
        url: str | None = f"{base}?page={start_page + 1}" if start_page else base
        company = name_from_slug(task.board)
        for _ in range(MAX_PAGES):
            if not url:
                return
            data = await http.get_json(url)
            yield [s for p in data.get("results") or [] if (s := self.stub(p, task.board, company))]
            url = data.get("next")

    @staticmethod
    def stub(p: dict[str, Any], board: str, company: str) -> JobStub | None:
        job_hash = p.get("hash")  # the public posting id; without it there is nothing to key on
        title = " ".join(str(p.get("position_name") or "").split())
        if not job_hash or not title:
            return None
        location = p.get("location_display") or ", ".join(
            x for x in (p.get("city"), p.get("state"), p.get("country")) if x
        )
        url = f"https://www.careers-page.com/{quote(board, safe='')}/job/{job_hash}"
        return JobStub(
            source="manatal",
            url=url,
            title=title,
            company=company,
            location=location,
            description=strip_html(p.get("description") or ""),
            ats="manatal",
            apply_url=url,
            remote="remote" if p.get("is_remote") else remote_from_text(location),
            extra={"board": board, "id": job_hash, "employment": p.get("contract_details")},
        )
