"""Darwinbox careers ({tenant}.darwinbox.in or .com /ms/candidatev2/{companyId}/careers). The
board is "host/companyId"; the page's own JSON API lists postings 50 at a time, newest first,
bodies inline. `posted_on` is epoch seconds. Salary is kept only when stated per year.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, name_from_host, safe_date

LIST = "https://{host}/ms/candidateapi/job/alljobs?companyId={company}"
JOB = "https://{host}/ms/candidatev2/{company}/careers/jobDetails/{id}"
PAGE = 50
MAX_PAGES = 200


def _amount(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class Darwinbox(Source):
    name = "darwinbox"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"([a-z0-9][a-z0-9-]*\.darwinbox\.(?:in|com))/ms/candidatev2/([a-z0-9_-]+)/careers",
            re.I,
        ),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, _, company = task.board.partition("/")
        url = LIST.format(host=host, company=company)
        for page in range(start_page + 1, MAX_PAGES + 1):
            body = {"companyId": company, "page": page, "sort_option": "new", "limit": PAGE}
            data = await http.post_json(url, body)
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list) or data.get("status") != "success":
                raise ValueError("darwinbox: the response is not a successful data array")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r, task.board))]
            if stubs:
                yield stubs
            if len(rows) < PAGE:
                return

    @staticmethod
    def location(r: dict[str, Any]) -> str:
        """Every listed place; `locations` alone reads "Multiple Locations" on such a posting."""
        tips = r.get("tool_tip_locations")
        places = tips if isinstance(tips, list) and tips else [r.get("locations")]
        labels = (clean(p).replace(" ,", ",") for p in places if isinstance(p, str))
        return "; ".join(dict.fromkeys(x for x in labels if x))

    @classmethod
    def stub(cls, r: dict[str, Any], board: str) -> JobStub | None:
        host, _, company = board.partition("/")
        title, jid = clean(r.get("title")), str(r.get("id") or "").strip()
        if not title or not jid:
            return None
        url = JOB.format(host=host, company=company, id=quote(jid, safe=""))
        posted = r.get("posted_on")
        where = cls.location(r)
        stub = JobStub(
            source="darwinbox",
            url=url,
            title=title,
            company=name_from_host(host),
            location=where,
            description=strip_html(r.get("jd") or ""),
            posted_at=(
                from_epoch_ms(posted * 1000)
                if isinstance(posted, int | float) and posted > 0
                else safe_date(r.get("created_on"))
            ),
            ats="darwinbox",
            apply_url=url,
            remote=remote_from_text(where),
            extra={"board": board, "id": jid, "code": r.get("internal_job_code")},
        )
        low, high = _amount(r.get("salary_min")), _amount(r.get("salary_max"))
        if str(r.get("salary_timeframe") or "").strip().lower() == "annual" and (low or high):
            stub.salary_min, stub.salary_max, stub.salary_interval = low, high, "year"
            stub.salary_currency = str(r.get("salary_currency") or "").strip().upper() or None
        return stub
