"""HigherMe (app.higherme.com), the hourly-workforce ATS for restaurants, hotels and retail: a
keyless paged JSON API that returns every posting of a brand with its body. Logic adapted from
freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f12 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://api.higherme.com/classic/jobs"
PAGE_SIZE = 100  # the API clamps a larger limit
MAX_PAGES = 50
_CURRENCY = {"US": "USD", "CA": "CAD"}  # the platform runs in these two countries only


class HigherMe(Source):
    """The board is a brand id, the 13-hex reference in app.higherme.com/careers/<brand>. A
    posting's own URL names no brand, so only the careers URL is recognised."""

    name = "higherme"
    kind = "ats"
    url_patterns = (re.compile(r"app\.higherme\.com/careers/(\w+)", re.I),)
    # ponytail: the default 2 req/s per host; freehire paces this API to one request per 3 s.

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        brand = task.board
        for page in range(start_page + 1, MAX_PAGES + 1):
            params = {
                "page": page,
                "limit": PAGE_SIZE,
                "includes": "location,location.brand",
                "filters[brand.id]": brand,
            }
            data = await http.get_json(API, params=params)
            rows = data.get("data") or []
            for r in rows:
                # An ignored filter answers with the whole platform: never file that under one
                # employer.
                got = self._brand(r).get("id")
                if got != brand:
                    raise ValueError(
                        f"higherme: asked for brand {brand!r}, got a posting of {got!r}"
                    )
            yield [s for r in rows if (s := self.stub(r, brand))]
            if not rows or page >= (data.get("meta") or {}).get("last_page", 0):
                return

    @staticmethod
    def _location(r: dict[str, Any]) -> dict[str, Any]:
        return ((r.get("relations") or {}).get("location")) or {}

    @classmethod
    def _brand(cls, r: dict[str, Any]) -> dict[str, Any]:
        return (cls._location(r).get("relations") or {}).get("brand") or {}

    @classmethod
    def stub(cls, r: dict[str, Any], board: str) -> JobStub | None:
        a = r.get("attributes") or {}
        if not r.get("id") or a.get("status") != "published":
            return None
        loc = cls._location(r).get("attributes") or {}
        country = (loc.get("country") or {}).get("short") or ""
        place = (
            loc.get("city"),
            (loc.get("state") or {}).get("name"),
            (loc.get("country") or {}).get("name"),
        )
        location = ", ".join(p for p in place if p)
        reqs = "".join(
            f"<li>{html.escape(q.strip())}</li>" for q in a.get("requirements") or [] if q.strip()
        )
        blocks = [
            html_to_text(a.get("summary") or ""),
            "Requirements\n" + html_to_text(f"<ul>{reqs}</ul>") if reqs else "",
            "About\n" + html_to_text(a["about"]) if a.get("about") else "",
        ]
        salary = a.get("salary") or {}
        currency = (
            _CURRENCY.get(country.upper()) if salary.get("min") or salary.get("max") else None
        )
        # No posted_at: the API states only updated_at, which is re-stamped on every edit.
        url = f"https://app.higherme.com/jobs/{r['id']}"
        return JobStub(
            source="higherme",
            url=url,
            title=" ".join((a.get("title") or "").split()),
            # The posting's own "company" is an internal account label (one per franchisee
            # group); the brand is what the career page presents as the employer.
            company=(cls._brand(r).get("attributes") or {}).get("name") or name_from_slug(board),
            location=location,
            description="\n\n".join(b for b in blocks if b),
            ats="higherme",
            apply_url=url,
            remote=remote_from_text(location),
            salary_min=salary.get("min") if currency else None,
            salary_max=salary.get("max") if currency else None,
            salary_currency=currency,
            salary_interval=("hour" if salary.get("type") == "hourly" else "year")
            if currency
            else None,
            extra={
                "board": board,
                "id": r["id"],
                "full_time": a.get("full_time"),
                "part_time": a.get("part_time"),
            },
        )
