"""FriendWork (friend.work), a Russian ATS: one keyless call returns a tenant's whole career
portal with descriptions. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode, name_from_slug

API = "https://api.friend.work/Publication/CareerPortal"
SITE = "https://jobs.friend.work"
# The portal renders every amount per month; the currency is the platform's numeric enum.
CURRENCY = {0: "RUB", 1: "USD", 2: "EUR", 3: "UAH", 4: "KZT", 5: "BYN", 6: "AED", 7: "UZS"}


class FriendWork(Source):
    """The board is the portal token: a readable alias (`tedo`) or a 32-hex hash."""

    name = "friendwork"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.friend\.work/([\w-]+)", re.I),)
    # ponytail: the API drew 429s from two parallel workers, so one board at a time.

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # page/perPage are ignored by the API: one answer holds everything
            return
        data = await http.get_json(API, params={"token": task.board})
        company = (data.get("company") or {}).get("name") or name_from_slug(task.board)
        yield [
            self.stub(p, task.board, company)
            for p in data.get("publications") or []
            if p.get("publishedJobId") and p.get("title")
        ]

    @staticmethod
    def stub(p: dict[str, Any], board: str, company: str) -> JobStub:
        jid = str(p["publishedJobId"])
        path = p.get("externalPublicationUrl") or f"/{board}/{jid}"
        url = SITE + path
        location = p.get("city") or p.get("address") or ""
        low, high = (p.get("salaryFrom") or 0) or None, (p.get("salaryTo") or 0) or None
        currency = CURRENCY.get(p.get("currency"))  # type: ignore[arg-type]
        paid = currency is not None and (low or high)
        return JobStub(
            source="friendwork",
            url=url,
            title=p["title"].strip(),
            company=company,
            location=location,
            description=strip_html(p.get("description") or ""),
            posted_at=from_iso(p.get("publishDateTime") or p.get("dateCreated")),
            ats="friendwork",
            apply_url=url,
            remote=mode(p.get("workplaceType")) or remote_from_text(location),
            salary_min=low if paid else None,
            salary_max=high if paid else None,
            salary_currency=currency if paid else None,
            salary_interval="month" if paid else None,
            extra={"board": board, "id": jid},
        )
