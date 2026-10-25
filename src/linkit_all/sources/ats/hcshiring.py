"""symplr (HealthcareSource) career centers ({board}.hcshiring.com): a paged JSON listing and a
JSON description per posting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

BASE = "https://{board}.hcshiring.com"
MAX_PAGES = 500  # ten rows a page; a board that never reports its last page must not loop
_URL = re.compile(r"//([\w-]+)\.hcshiring\.com/jobs/([\w-]+)", re.I)
# The tenant types its Salary field; only the platform's "38.50 - 55.71 Hourly" shape is read.
_SALARY = re.compile(r"^(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?\s+([A-Za-z]+)$")
_PERIOD = {
    "hourly": "hour",
    "daily": "day",
    "monthly": "month",
    "annually": "year",
    "yearly": "year",
}


class HcsHiring(Source):
    """The board is the tenant subdomain: `regencypark` for regencypark.hcshiring.com."""

    name = "hcshiring"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!www\.)([\w-]+)\.hcshiring\.com", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.lower()
        company = name_from_slug(board)
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(f"{BASE.format(board=board)}/api/jobs?page={page}")
            rows = data.get("jobs")
            if rows is None:
                raise ValueError(f"hcshiring: no jobs array on page {page} of {board}")
            # Internal-only rows are open to the tenant's employees alone.
            yield [
                self.stub(r, board, company)
                for r in rows
                if r.get("id") and not r.get("isInternalOnly")
            ]
            if not rows or page >= (data.get("meta") or {}).get("totalPages", 0):
                return

    @staticmethod
    def stub(r: dict[str, Any], board: str, company: str) -> JobStub:
        # "City, ST ZIP"
        place = [
            (r.get("city") or "").strip(),
            " ".join(f"{r.get('state') or ''} {r.get('zip') or ''}".split()),
        ]
        location = ", ".join(p for p in place if p)
        fields = r.get("publicFieldValues") or []
        status = next((f["value"] for f in fields if f.get("standardName") == "Status"), "")
        pay = next(
            (f["value"] for f in fields if (f.get("name") or "").strip().lower() == "salary"), ""
        )
        lo, hi, interval = _salary(pay)
        return JobStub(
            source="hcshiring",
            url=f"{BASE.format(board=board)}/jobs/{r['id']}",
            title=" ".join((r.get("title") or "").split()),
            company=company,
            location=location,
            posted_at=from_iso(r.get("lastOpening")),
            ats="hcshiring",
            remote=remote_from_text(location),
            salary_min=lo,
            salary_max=hi,
            salary_currency="USD" if interval else None,  # US employers only
            salary_interval=interval,
            extra={"board": board, "id": r["id"], "employment": status or None},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        url = f"{BASE.format(board=m[1])}/api/jobDescriptions?id={quote(m[2])}"
        resp = await http.get(url)
        if resp.status_code in (404, 410):
            return stub
        resp.raise_for_status()
        text = html_to_text((resp.json().get("jobDescriptions") or {}).get("description") or "")
        return stub.model_copy(update={"description": text}) if text else stub


def _salary(value: str) -> tuple[float | None, float | None, str | None]:
    m = _SALARY.match((value or "").strip())
    interval = _PERIOD.get(m[3].lower()) if m else None
    if not m or not interval:  # "Weekly" and the like have no interval to state it in
        return None, None, None
    low = float(m[1])
    return low, float(m[2] or low), interval
