"""PyjamaHR (jobs.pyjamahr.com), an Indian multi-tenant ATS, read through its career API on
api.pyjamahr.com. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import GONE, hydrate
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode, name_from_slug, when
from linkit_all.sources.text import html_to_text

API = "https://api.pyjamahr.com/api/career/jobs/"
JOB_URL = "https://jobs.pyjamahr.com/{board}/{slug}"
PAGE = 20  # postings per yielded page: their detail fetches run together
MAX_PAGES = 500  # safety ceiling on the list's own "next" chain
_PERIOD = {"ANNUAL": "year", "MONTHLY": "month"}


class PyjamaHR(Source):
    """The board is the company slug in `jobs.pyjamahr.com/<slug>`. The list is DRF-paged (its own
    `next` link); the description and salary are only on the per-posting detail."""

    name = "pyjamahr"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.pyjamahr\.com/([\w-]+)", re.I),)
    cdx_hosts = ("jobs.pyjamahr.com/*",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board
        items: list[dict[str, Any]] = []
        nxt = f"{API}?company_slug={board}&page=1"
        for _ in range(MAX_PAGES):
            data = await http.get_json(nxt)
            items += [i for i in data.get("results") or [] if i.get("id") and i.get("slug")]
            if not (nxt := data.get("next")):
                break
        else:
            raise ValueError(f"pyjamahr: {board}: no end to the list after {MAX_PAGES} pages")
        company = name_from_slug(board)

        async def build(item: dict[str, Any]) -> JobStub:
            stub = self.stub(item, board, company)
            try:
                detail = await http.get_json(f"{API}{item['id']}/?company_slug={board}")
            except GONE:
                return stub  # keep the posting; it just has no description
            return self.with_detail(stub, detail)

        async for page in hydrate(items, start_page, build, PAGE):
            yield page

    @staticmethod
    def stub(i: dict[str, Any], board: str, company: str) -> JobStub:
        url = JOB_URL.format(board=board, slug=i["slug"])
        where = i.get("location") or ""
        return JobStub(
            source="pyjamahr",
            url=url,
            title=(i.get("title") or "").strip(),
            company=company,
            location=where,
            ats="pyjamahr",
            apply_url=url,
            remote=mode((i.get("workplace_type") or "").replace("_", "-"))
            or remote_from_text(i.get("title"), where),
            extra={"board": board, "id": str(i["id"])},
        )

    @staticmethod
    def with_detail(stub: JobStub, d: dict[str, Any]) -> JobStub:
        upd: dict[str, Any] = {
            "description": html_to_text(d.get("description") or ""),
            "posted_at": when(d.get("created_at")),
            "extra": {
                **stub.extra,
                "employment": d.get("job_type"),
                "skills": d.get("skill") or [],
            },
        }
        if d.get("remote"):
            upd["remote"] = "remote"
        # Bounds only with a visible flag and a known unit: a guessed unit would misstate the pay.
        period = _PERIOD.get(str(d.get("salary_type") or "").upper())
        lo, hi = d.get("min_salary"), d.get("max_salary")
        if d.get("is_salary_visible") and period and lo is not None and hi is not None:
            upd |= {
                "salary_min": lo,
                "salary_max": hi,
                "salary_currency": d.get("currency"),
                "salary_interval": period,
            }
        return stub.model_copy(update=upd)
