"""Hireology career sites (careers.hireology.com): a public JSON:API with every posting and its
description. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f12 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://api.hireology.com/v1/careers/{board}"


class Hireology(Source):
    """The board is the tenant slug: `acme` for careers.hireology.com/acme."""

    name = "hireology"
    kind = "ats"
    url_patterns = (
        re.compile(r"api\.hireology\.com/v1/careers/([\w-]+)", re.I),
        re.compile(r"careers\.hireology\.com/([\w-]+)", re.I),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = await http.get_json(API.format(board=task.board))
        company = name_from_slug(task.board)
        yield [
            self.stub(d["id"], d["attributes"], task.board, company)
            for d in data.get("data") or []
            if d.get("id") and (d.get("attributes") or {}).get("status", "").lower() == "open"
        ]

    @staticmethod
    def stub(job_id: str, a: dict[str, Any], board: str, company: str) -> JobStub:
        location = ", ".join(x.strip() for x in a.get("locations") or [] if x and x.strip())
        default = f"https://careers.hireology.com/{board}/{job_id}/description"
        url = a.get("career-site-url") or default
        return JobStub(
            source="hireology",
            url=url,
            title=" ".join((a.get("name") or "").split()),
            company=company,
            location=location,
            description=html_to_text(a.get("job-description") or ""),
            ats="hireology",
            apply_url=url,
            remote="remote" if a.get("remote") else remote_from_text(location),
            extra={"board": board, "id": str(job_id)},
        )
