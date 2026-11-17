"""Jobstreet (Indonesia, Singapore, Malaysia) and JobsDB (Hong Kong), SEEK's Asian boards, through
the v5 job search API their own pages call. Our `seek` plugin covers Australia and New Zealand
on the same platform; this one covers the other markets. One task per search query and market;
a market is picked when a search place names its country, else Indonesia. The list has a
teaser, not the full body. Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, mode, safe_date
from linkit_all.sources.tasks import all_older, limited

# market: (origin, site key, job path, country words a search place may use)
MARKETS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "id": ("https://id.jobstreet.com", "ID-Main", "/id/job/", ("indonesia", "jakarta")),
    "sg": ("https://sg.jobstreet.com", "SG-Main", "/job/", ("singapore",)),
    "my": ("https://my.jobstreet.com", "MY-Main", "/job/", ("malaysia", "kuala lumpur")),
    "hk": ("https://hk.jobsdb.com", "HK-Main", "/job/", ("hong kong",)),
}
PAGE = 100
MAX_PAGES = 50


def markets_for(places: list[str]) -> list[str]:
    """The markets the search places name; Indonesia when none does."""
    text = " ".join(places).lower()
    return [m for m, (*_, words) in MARKETS.items() if any(w in text for w in words)] or ["id"]


class Jobstreet(Source):
    name = "jobstreet"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        s = cfg.search
        return [
            Task(self.name, f"{self.name}:{q}@{m}", query=q, country=m,
                 limit=s.max_results_per_query, posted_within_days=s.posted_within_days)
            for q in s.queries
            for m in markets_for(s.locations)
        ]  # fmt: skip

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        market = task.country if task.country in MARKETS else "id"
        origin, site_key, _, _ = MARKETS[market]
        for page in range(start_page + 1, MAX_PAGES + 1):
            params = {"siteKey": site_key, "keywords": task.query, "pageSize": PAGE, "page": page}
            data = await http.get_json(f"{origin}/api/jobsearch/v5/search", params=params)
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("jobstreet: the response carries no data array")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r, market))]
            yield stubs
            total = data.get("totalCount")
            if len(rows) < PAGE or (isinstance(total, int) and page * PAGE >= total):
                return
            if all_older(stubs, task):
                return

    def stub(self, r: dict[str, Any], market: str) -> JobStub | None:
        origin, _, path, _ = MARKETS[market]
        jid, title = str(r.get("id") or "").strip(), clean(r.get("title"))
        company = clean((r.get("advertiser") or {}).get("description") or r.get("companyName"))
        if not (jid and title and company):
            return None
        url = f"{origin}{path}{quote(jid, safe='')}"
        places = r.get("locations") or []
        where = clean(places[0].get("label")) if places and isinstance(places[0], dict) else ""
        arrangement = ((r.get("workArrangements") or {}).get("data") or [{}])[0]
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=where,
            description=clean(r.get("teaser")),
            posted_at=safe_date(r.get("listingDate")),
            ats=self.name,
            apply_url=url,
            remote=mode(str(((arrangement or {}).get("label") or {}).get("text") or "")),
            extra={"id": jid, "market": market, "salary_text": clean(r.get("salaryLabel"))},
        )
