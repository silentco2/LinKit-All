"""TKMS (thyssenkrupp Marine Systems) careers at jobs.tkmsgroup.com: the page's own query API
lists postings 20 at a time (0-based pages, `nextPage` null on the last). The public page is
{origin}/en/job/{slug}/{id}; the slug is cosmetic, so it is built from the title. Titles come
HTML-escaped and are decoded. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date
from linkit_all.sources.tasks import careers_task
from linkit_all.sources.text import html_to_text

ORIGIN = "https://jobs.tkmsgroup.com"
API = f"{ORIGIN}/api/filter/query"
MAX_PAGES = 60


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "job"


class Tkms(Source):
    name = "tkms"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        page: Any = start_page
        for _ in range(MAX_PAGES):
            body = {
                "searchQuery": "",
                "filter": {},
                "subclient": "tkms",
                "locale": "en",
                "page": page,
            }
            data = await http.post_json(API, body)
            rows = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("tkms: the response carries no jobs array")
            yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r.get("data") or {}))]
            page = data.get("nextPage")
            if not isinstance(page, int) or not rows:
                return

    def stub(self, d: dict[str, Any]) -> JobStub | None:
        jid, title = str(d.get("id") or "").strip(), clean(html_to_text(str(d.get("title") or "")))
        if not (jid and title):
            return None
        places = [
            clean(p.get("cityState") or p.get("city"))
            for p in d.get("locations") or []
            if isinstance(p, dict)
        ]
        where = " / ".join(dict.fromkeys(p for p in places if p)) or ", ".join(
            dict.fromkeys(x for x in (clean(d.get("city")), clean(d.get("country"))) if x)
        )
        stamp = d.get("postingDate_timestamp")
        url = f"{ORIGIN}/en/job/{slugify(title)}/{jid}"
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=clean(d.get("company")) or "thyssenkrupp Marine Systems",
            location=where,
            posted_at=from_epoch_ms(stamp * 1000)
            if isinstance(stamp, int | float)
            else safe_date(d.get("postingDate")),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(where, title),
            extra={"id": jid},
        )
