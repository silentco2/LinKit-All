"""HiBob careers ({board}.careers.hibob.com): one keyless call returns the whole board with its
descriptions. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f12 import mode, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://{board}.careers.hibob.com/api/job-ad"
SITE = "https://{board}.careers.hibob.com/jobs"
_SECTIONS = (
    ("", "description"),
    ("Responsibilities", "responsibilities"),
    ("Requirements", "requirements"),
    ("Benefits", "benefits"),
)


class HiBob(Source):
    """The board is the tenant slug: `qogita` for qogita.careers.hibob.com."""

    name = "hibob"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.careers\.hibob\.com", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        board = task.board.lower()
        # The careers page's own front end sends this Referer; the API answers 401 without it.
        referer = {"Referer": SITE.format(board=board)}
        data = await http.get_json(API.format(board=board), headers=referer)
        company = name_from_slug(board)
        yield [self.stub(a, board, company) for a in data.get("jobAdDetails") or [] if a.get("id")]

    @staticmethod
    def stub(a: dict[str, Any], board: str, company: str) -> JobStub:
        blocks = []
        for heading, key in _SECTIONS:
            if text := html_to_text(a.get(key) or ""):
                blocks.append(f"{heading}\n{text}" if heading else text)
        url = f"{SITE.format(board=board)}/{a['id']}"
        place = (a.get("site"), a.get("country"))
        location = ", ".join(p.strip() for p in place if p and p.strip())
        return JobStub(
            source="hibob",
            url=url,
            title=" ".join((a.get("title") or "").split()),
            company=company,
            location=location,
            description="\n\n".join(blocks),
            posted_at=from_iso(a.get("publishedAt")),
            ats="hibob",
            apply_url=url,
            remote=mode(a.get("workspaceType")) or remote_from_text(location),
            extra={"board": board, "id": a["id"], "department": a.get("department")},
        )
