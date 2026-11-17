"""PrevueAPS careers pages ({board}.prevueaps.ca). The public JSON endpoint is keyed by a small
numeric site id, not the subdomain; the id is read from the tenant's own /jobs/ page (its
script builds the very URL called here). The list has no body.
Logic adapted from career-ops (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, last_segment, name_from_slug

ORIGIN = "https://{board}.prevueaps.ca"
_SHOW = {
    "showDate": True,
    "showLocation": True,
    "showEmploymentType": True,
    "showCategory": True,
    "showClassification": True,
    "showWorkplaceType": True,
    "customCategoryTitle": "",
}
# Most direct signal first: the URL the page itself calls, then the ids it is built from.
_SITE_ID = (
    re.compile(r"/core/jobs/(\d+)"),
    re.compile(r"data-domain-id\s*=\s*[\"'](\d+)[\"']", re.I),
    re.compile(r"[\"']?domainId[\"']?\s*[:=]\s*[\"']?(\d+)", re.I),
    re.compile(r"[\"']?siteId[\"']?\s*[:=]\s*[\"']?(\d+)", re.I),
)


class PrevueAPS(Source):
    name = "prevueaps"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([a-z0-9][a-z0-9-]*)\.prevueaps\.ca", re.I),)
    cdx_hosts = ("*.prevueaps.ca",)
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds the whole board
            return
        origin = ORIGIN.format(board=task.board.lower())
        page = (await get_page(http, f"{origin}/jobs/")).text
        site = next((m[1] for p in _SITE_ID if (m := p.search(page))), None)
        if site is None:
            raise ValueError("prevueaps: the jobs page carries no site id")
        data = await http.get_json(
            f"{origin}/core/jobs/{site}", params={"getParams": json.dumps(_SHOW)}
        )
        rows = (data.get("data") or {}).get("jobs") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError("prevueaps: the response carries no data.jobs array")
        stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r, task.board))]
        if stubs:
            yield stubs

    @staticmethod
    def stub(r: dict[str, Any], board: str) -> JobStub | None:
        title, url = clean(r.get("title")), str(r.get("jobUrl") or "").strip()
        if not title or not url.startswith("https://"):
            return None
        where = clean(r.get("jobLocation")) or ", ".join(
            x
            for x in (clean(r.get("city")), clean(r.get("abbreviation") or r.get("stateName")))
            if x
        )
        facts = [clean(r.get(k)) for k in ("employmentType", "classification")]
        low, high = clean(r.get("minSalary")), clean(r.get("maxSalary"))
        if low or high:
            pay = " - ".join(x for x in (low, high) if x)
            facts.append(f"{pay} {clean(r.get('payTypeFrame'))}".strip())
        return JobStub(
            source="prevueaps",
            url=url,
            title=title,
            company=name_from_slug(board),
            location=where,
            description=" · ".join(f for f in facts if f),
            ats="prevueaps",
            apply_url=url,
            remote=remote_from_text(where, clean(r.get("workplaceType"))),
            extra={"board": board, "id": str(r.get("id") or last_segment(url))},
        )
