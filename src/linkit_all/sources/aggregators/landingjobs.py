"""landing.jobs, a European tech job board. One public feed, body inline; the employer is only in
the posting URL (`/at/<company>/<job>`). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

API = "https://landing.jobs/api/v1/jobs"
_COMPANY = re.compile(r"/at/([^/?#]+)/[^/?#]+")
SECTIONS = (
    ("role_description", ""), ("main_requirements", "Requirements"),
    ("nice_to_have", "Nice to have"), ("perks", "Perks"),
)  # fmt: skip


def company_from_url(url: str) -> str:
    """ ".../at/acme-corp/senior-go" -> "Acme Corp"; "" for a URL without both segments."""
    m = _COMPANY.search(url)
    words = re.split(r"[-_\s]+", m[1]) if m else []
    return " ".join(w[0].upper() + w[1:] for w in words if w)


class LandingJobs(Source):
    name = "landingjobs"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # ponytail: `?page=` is ignored by the endpoint, so the one response is the whole feed
        rows = await http.get_json(API)
        if start_page == 0:
            stubs = [s for r in rows[: task.limit] if (s := self.stub(r))]
            if stubs:
                yield stubs

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        url, company = p.get("url") or "", company_from_url(p.get("url") or "")
        if not (p.get("id") and p.get("title") and company):
            return None
        places = []
        for loc in p.get("locations") or []:  # several cities for a role open in more than one
            label = ", ".join(
                x for x in ((loc.get("city") or "").strip(), loc.get("country_code")) if x
            )
            if label and label not in places:
                places.append(label)
        if p.get("remote"):
            places.append("Remote")
        body = "".join(
            (f"<h3>{head}</h3>" if head else "") + p[key]
            for key, head in SECTIONS
            if (p.get(key) or "").strip()
        )
        stub = JobStub(
            source=self.name,
            url=url,
            title=p["title"].strip(),
            company=company,
            location="; ".join(places),
            description=strip_html(body),
            posted_at=from_iso(p.get("published_at") or p.get("created_at")),
            ats=self.name,
            apply_url=url,
            remote="remote" if p.get("remote") else None,  # not flagged remote is not onsite
            extra={"id": p["id"]},
        )
        low, high, cur = (
            p.get("gross_salary_low"),
            p.get("gross_salary_high"),
            p.get("currency_code"),
        )
        if (low or high) and cur:  # the feed states gross yearly pay
            stub.salary_min, stub.salary_max = low, high
            stub.salary_currency, stub.salary_interval = cur, "year"
        return stub
