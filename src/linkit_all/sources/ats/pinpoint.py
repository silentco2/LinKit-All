"""Pinpoint public postings feed ({board}.pinpointhq.com/postings.json). Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import mode, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

FEED = "https://{board}.pinpointhq.com/postings.json"
# The posting body is split over several HTML sections of the same record.
_BODY = ("description", "key_responsibilities", "skills_knowledge_expertise", "benefits")


class Pinpoint(Source):
    name = "pinpoint"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!www\.)([\w-]+)\.pinpointhq\.com", re.I),)
    cdx_hosts = ("*.pinpointhq.com",)
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds every posting, descriptions included
            return
        data = await http.get_json(FEED.format(board=task.board))
        company = name_from_slug(task.board)
        yield [self.stub(d, task.board, company) for d in data.get("data") or [] if d.get("url")]

    @staticmethod
    def stub(d: dict[str, Any], board: str, company: str) -> JobStub:
        loc = d.get("location") or {}
        # city/province first; some boards fill only the display name ("Remote").
        where = ", ".join(p for p in (loc.get("city"), loc.get("province")) if p) or (
            loc.get("name") or ""
        )
        kind = d.get("workplace_type")
        return JobStub(
            source="pinpoint",
            url=d["url"],
            title=(d.get("title") or "").strip(),
            company=company,
            location=where,
            description=html_to_text("".join(d.get(k) or "" for k in _BODY)),
            ats="pinpoint",
            apply_url=d["url"],
            remote=mode(kind) or remote_from_text(where),
            extra={"board": board, "id": str(d.get("id") or "")},
        )
