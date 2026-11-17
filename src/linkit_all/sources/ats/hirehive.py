"""HireHive public jobs API ({board}.hirehive.com/api/v2/jobs): 100 postings a page, bodies
inline. A group board can list postings of sister tenants; their own page stays the job URL.
Pay is read only from a tier the posting page shows (range or fixed) and only when per year.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, name_from_slug, safe_date

API = "https://{board}.hirehive.com/api/v2/jobs"
PAGE = 100
MAX_PAGES = 100
_SHOWN = {"range_salary", "fixed_salary"}


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class HireHive(Source):
    name = "hirehive"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"(?<![\w.-])(?!(?:www|app|accounts|apply)\.)([a-z0-9][a-z0-9-]*)\.hirehive\.com", re.I
        ),
    )
    cdx_hosts = ("*.hirehive.com",)
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        company = name_from_slug(task.board)
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(
                API.format(board=task.board), params={"page": page, "page_size": PAGE}
            )
            rows = data.get("items") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("hirehive: the response carries no items array")
            stubs = [
                s for r in rows if isinstance(r, dict) and (s := self.stub(r, task.board, company))
            ]
            if stubs:
                yield stubs
            if len(rows) < PAGE or (data.get("meta") or {}).get("has_next_page") is False:
                return

    @staticmethod
    def stub(r: dict[str, Any], board: str, company: str) -> JobStub | None:
        title, url = clean(r.get("title")), str(r.get("hosted_url") or "")
        parts = urlsplit(url)
        if (
            not title
            or parts.scheme != "https"
            or not (parts.hostname or "").endswith(".hirehive.com")
        ):
            return None
        country = clean((r.get("country") or {}).get("name"))
        place = clean(r.get("location"))
        where = (
            place
            if country.lower() in place.lower()
            else ", ".join(p for p in (place, country) if p)
        )
        body = r.get("description") or {}
        stub = JobStub(
            source="hirehive",
            url=url,
            title=title,
            company=company,
            location=where,
            description=strip_html(body.get("html") or "") or str(body.get("text") or "").strip(),
            posted_at=safe_date(r.get("published_date")),
            ats="hirehive",
            apply_url=url,
            remote=remote_from_text(where),
            extra={"board": board, "id": str(r.get("id") or "")},
        )
        for tier in r.get("compensation_tiers") or []:
            if not isinstance(tier, dict) or tier.get("type") not in _SHOWN:
                continue
            low, high = _positive(tier.get("min_value")), _positive(tier.get("max_value"))
            if tier.get("interval") == "year" and (low or high):
                bounds = sorted(x for x in (low or high, high or low) if x)
                stub.salary_min, stub.salary_max, stub.salary_interval = (
                    bounds[0],
                    bounds[-1],
                    "year",
                )
                stub.salary_currency = clean(tier.get("currency_code")).upper() or None
                break
        return stub
