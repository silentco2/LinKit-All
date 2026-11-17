"""ClearCompany career-site API (careers-api.clearcompany.com/v1/{siteId}). The board is the
site GUID a tenant's careers page carries in its embed script. Pages are 0-based; the server may
clamp the page size, so only an empty page, a repeated page or the reported total ends the walk.
A posting's only address is its apply link; email-to-apply rows have none and are dropped.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date

API = "https://careers-api.clearcompany.com/v1/{board}"
PAGE = 100
MAX_PAGES = 300
_GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class ClearCompany(Source):
    name = "clearcompany"
    kind = "ats"
    url_patterns = (
        re.compile(rf"careers-api\.clearcompany\.com/v1/({_GUID})", re.I),
        re.compile(rf"careers-content\.clearcompany\.com/[^\s\"'<>]*?siteid=({_GUID})", re.I),
    )
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        url = API.format(board=task.board.lower())
        seen_rows, last_ids = start_page * PAGE, None
        for page in range(start_page, MAX_PAGES):
            data = await http.get_json(url, params={"pageIndex": page, "pageSize": PAGE})
            rows = data.get("results") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("clearcompany: the response carries no results array")
            ids = [r.get("id") if isinstance(r, dict) else None for r in rows]
            if not rows or ids == last_ids:  # past the end, or a server that ignores pageIndex
                return
            yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r, task.board))]
            seen_rows, last_ids = seen_rows + len(rows), ids
            total = data.get("totalCount")
            if isinstance(total, int) and seen_rows >= total:
                return

    @staticmethod
    def location(r: dict[str, Any]) -> str:
        if isinstance(r.get("location"), str) and r["location"].strip():
            return str(r["location"]).strip()
        first = next((x for x in r.get("locations") or [] if isinstance(x, dict)), {})
        parts = (first.get("city"), first.get("subdivisionFullName") or first.get("subdivision"))
        place = ", ".join(p.strip() for p in (*parts, first.get("country")) if p and p.strip())
        if first.get("isRemote") is True:
            return f"Remote ({place})" if place else "Remote"
        return place

    @classmethod
    def stub(cls, r: dict[str, Any], board: str) -> JobStub | None:
        title, url = clean(r.get("positionTitle")), str(r.get("applyLink") or "").strip()
        if not title or not url.startswith("https://"):
            return None
        where = cls.location(r)
        return JobStub(
            source="clearcompany",
            url=url,
            title=title,
            company=clean(r.get("brandName")) or board,
            location=where,
            description=strip_html(r.get("description") or ""),
            posted_at=safe_date(r.get("postedDate")) or safe_date(r.get("openDate")),
            ats="clearcompany",
            apply_url=url,
            remote="remote" if where.startswith("Remote") else None,
            extra={"board": board, "id": str(r.get("userDefinedId") or r.get("id") or "")},
        )
