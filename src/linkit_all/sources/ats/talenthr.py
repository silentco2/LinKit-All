"""TalentHR career sites (jobs.talenthr.io/{board}): a Next.js app whose __NEXT_DATA__ lists the
positions on the board page and holds the full record on each position's page. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Remote, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.common import fetch_html, get_page, paged_postings, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug, next_data, safe_date

_BASE = "https://jobs.talenthr.io"
_ID = re.compile(r"/(\d+)/?$")  # .../{board}/{slug}/{id}
_MODES: dict[str, Remote] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "on site": "onsite",
}


def _props(html: str) -> dict[str, Any]:
    data = next_data(html) or {}
    return (data.get("props") or {}).get("pageProps") or {}


class TalentHR(Source):
    name = "talenthr"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.talenthr\.io/([\w-]+)", re.I),)
    cdx_hosts = ("jobs.talenthr.io/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board
        positions = _props((await get_page(http, f"{_BASE}/{board}")).text).get("positions")
        if positions is None:
            raise Unsupported(f"talenthr: no job data on the {board} board page")
        urls = [
            f"{_BASE}/{board}/{p['slug']}/{p['id']}"
            for p in positions
            if p.get("slug") and p.get("id")
        ]

        async def build(url: str) -> JobStub | None:
            html, m = await fetch_html(http, url), _ID.search(url)
            job = _props(html).get("data") if html else None
            title = " ".join(str((job or {}).get("job_position_title") or "").split())
            if not job or not title or m is None:
                return None
            place = [str(job.get(k) or "").strip() for k in ("city", "region", "country")]
            location = ", ".join(p for p in place if p) or str(
                job.get("location_address") or job.get("location_name") or ""
            )
            mode = _MODES.get(str(job.get("employment_type") or "").strip().lower())
            return JobStub(
                source=self.name,
                url=url,
                title=title,
                company=name_from_slug(board),
                location=location,
                description=strip_html(job.get("job_description") or ""),
                posted_at=safe_date(job.get("publish_date") or job.get("created_at")),
                ats=self.name,
                apply_url=url,
                remote=mode or ("remote" if job.get("is_remote") else remote_from_text(location)),
                extra={"board": board, "id": m[1]},
            )

        async for stubs in paged_postings(urls, start_page, build):
            yield stubs
