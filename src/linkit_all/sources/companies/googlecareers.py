"""Google's own careers site (google.com/about/careers/applications): the server-rendered results
pages inline their job payload in an AF_initDataCallback script block, so a paged list assembles
every posting with no detail request. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote_plus

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http

HOST = "www.google.com"
RESULTS = "https://{host}/about/careers/applications/jobs/results"
MAX_QUERIES = 5
# `data:[...], sideChannel`: lazy, so a posting body containing "], sideChannel" would truncate it
# and the JSON would fail to parse (an error, never silent bad data).
_DATA = re.compile(r"data:(\[.*?\]), sideChannel", re.S)


def payload(html: str) -> tuple[list[Any], int]:
    """(job records, catalogue size) from a results page. The records are positional arrays; a
    page past the last one has none."""
    for node in LexborHTMLParser(html).css("script"):
        text = node.text(deep=True)
        if "key: 'ds:1'" in text:  # other scripts mention the bare 'ds:1'
            m = _DATA.search(text)
            if not m:
                raise ValueError("google: ds:1 data array not found")
            data = json.loads(m[1])
            records = data[0] if data and isinstance(data[0], list) else []
            total = data[2] if len(data) > 2 and isinstance(data[2], int) else 0
            return records, total
    raise ValueError("google: ds:1 script not found")


def _at(rec: list[Any], i: int) -> Any:
    return rec[i] if i < len(rec) else None


def _html(rec: list[Any], i: int) -> str:
    """A [null, "<html>"] field, else ""."""
    pair = _at(rec, i)
    return pair[1] if isinstance(pair, list) and len(pair) > 1 and isinstance(pair[1], str) else ""


class GoogleCareers(Source):
    name = "googlecareers"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        # The site searches its catalogue (?q=); without queries, its default listing.
        return [
            Task(self.name, f"googlecareers:{q}", board=HOST, query=q)
            for q in cfg.search.queries[:MAX_QUERIES] or [""]
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        found = start_page * 20  # the page size is fixed at 20
        for page in range(start_page + 1, 1000):
            url = f"{RESULTS.format(host=task.board)}?page={page}"
            if task.query:
                url += f"&q={quote_plus(task.query)}"
            records, total = payload((await get_page(http, url)).text)
            if not records:
                return
            yield [s for r in records if isinstance(r, list) and (s := self.stub(r, task.board))]
            found += len(records)
            if found >= (min(total, task.limit) if total else task.limit):
                return

    def stub(self, rec: list[Any], host: str) -> JobStub | None:
        jid, title = _at(rec, 0), " ".join(str(_at(rec, 1) or "").split())
        if not jid or not title:
            return None
        locs = [loc[0] for loc in _at(rec, 9) or [] if isinstance(loc, list) and loc and loc[0]]
        posted = _at(rec, 12)
        url = f"{RESULTS.format(host=host)}/{jid}"
        # about the job, responsibilities, qualifications: the page's reading order
        body = _html(rec, 10) + _html(rec, 3) + _html(rec, 4)
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Google",
            location="; ".join(locs),
            description=strip_html(body),
            posted_at=from_epoch_ms(posted[0] * 1000)
            if isinstance(posted, list) and posted
            else None,
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(title, " ".join(locs)),
            extra={"id": str(jid), "brand": _at(rec, 7)},  # YouTube, DeepMind, Google Cloud ...
        )
