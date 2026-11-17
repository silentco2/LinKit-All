"""Polymer Hire (jobs.polymer.co/{board}) over its public JSON API. The paging metadata is not
trustworthy (`is_last`, `next_page` and `total` were all seen wrong), so the walk stops on an
empty or repeated page, or `is_last` on a page that has rows. The list has no body.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, name_from_slug, safe_date

API = "https://api.polymer.co/v1/hire/organizations/{board}/jobs"
JOB = "https://jobs.polymer.co/{board}/{id}"
MAX_PAGES = 100


class Polymer(Source):
    name = "polymer"
    kind = "ats"
    url_patterns = (
        re.compile(r"jobs\.polymer\.co/([a-z0-9][a-z0-9-]*)", re.I),
        re.compile(r"api\.polymer\.co/v1/hire/organizations/([a-z0-9][a-z0-9-]*)", re.I),
    )
    cdx_hosts = ("jobs.polymer.co/*",)
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.lower()
        last_ids: list[Any] | None = None
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(API.format(board=board), params={"page": page})
            rows = data.get("items") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("polymer: the response carries no items array")
            ids = [r.get("id") if isinstance(r, dict) else None for r in rows]
            if not rows or ids == last_ids:
                return
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r, board))]
            if stubs:
                yield stubs
            if (data.get("meta") or {}).get("is_last") is True:
                return
            last_ids = ids

    @staticmethod
    def stub(r: dict[str, Any], board: str) -> JobStub | None:
        title = clean(r.get("title"))
        jid = str(r.get("id") or r.get("job_id") or "").strip()
        url = str(r.get("job_post_url") or "").strip()
        if not url.startswith("https://"):
            url = JOB.format(board=board, id=quote(jid, safe="")) if jid else ""
        if not title or not url:
            return None
        place = clean(r.get("display_location")) or ", ".join(
            x for k in ("city", "state_region", "country") if (x := clean(r.get(k)))
        )
        kind = clean(r.get("remoteness_pretty"))
        stamp = r.get("published_at_timestamp")
        return JobStub(
            source="polymer",
            url=url,
            title=title,
            company=name_from_slug(board),
            location=place,
            posted_at=safe_date(r.get("published_at"))
            or (
                from_epoch_ms(stamp * 1000)
                if isinstance(stamp, int | float) and stamp > 0
                else None
            ),
            ats="polymer",
            apply_url=url,
            remote=remote_from_text(kind, place),
            extra={"board": board, "id": jid, "salary_text": clean(r.get("salary_pretty"))},
        )
