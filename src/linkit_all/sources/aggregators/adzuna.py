"""Adzuna job search API (api.adzuna.com): many employers in about 20 countries. Needs a free
app id + key (Setup → API keys); the free terms allow 250 calls a day, which this plugin counts.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from loguru import logger

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.keys import (
    COUNTRIES,
    DailyBudget,
    KeyGetter,
    get_keys,
    split_location,
)
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

URL = "https://api.adzuna.com/v1/api/jobs"
PAGE_SIZE = 50  # 100 answers HTTP 400
MAX_PAGES = 15
DAILY_BUDGET = 250  # Adzuna's free terms (2,500 a month)
CURRENCY = {  # Adzuna's markets, and the currency their pay figures are in
    "at": "EUR", "au": "AUD", "be": "EUR", "br": "BRL", "ca": "CAD", "ch": "CHF", "de": "EUR",
    "es": "EUR", "fr": "EUR", "gb": "GBP", "in": "INR", "it": "EUR", "mx": "MXN", "nl": "EUR",
    "nz": "NZD", "pl": "PLN", "sg": "SGD", "us": "USD", "za": "ZAR",
}  # fmt: skip
FIELDS = ("app_id", "app_key")


def _pay(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and value > 0 else None


def parse_job(item: dict[str, Any], country: str) -> JobStub | None:
    url, title = item.get("redirect_url"), item.get("title")
    if not url or not title:
        return None
    # A predicted salary is Adzuna's own estimate, not the posting's.
    predicted = str(item.get("salary_is_predicted")) == "1"
    low = None if predicted else _pay(item.get("salary_min"))
    high = None if predicted else _pay(item.get("salary_max"))
    location = (item.get("location") or {}).get("display_name") or ""
    return JobStub(
        source="adzuna",
        url=url,
        title=" ".join(str(title).split()),
        company=((item.get("company") or {}).get("display_name") or "").strip(),
        location=location,
        # The API only sends an excerpt; the full text is on the employer's site.
        description=strip_html(item.get("description") or ""),
        posted_at=from_iso(item.get("created")),
        apply_url=url,
        remote=remote_from_text(str(title), location),
        salary_min=low,
        salary_max=high,
        salary_currency=CURRENCY[country] if low or high else None,
        salary_interval="year" if low or high else None,
        ats="adzuna",
        extra={"id": str(item.get("id") or ""), "country": country},
    )


class Adzuna(Source):
    name = "adzuna"
    kind = "aggregator"
    parallel = 1  # every call spends the daily budget; serial keeps the count exact

    def __init__(self, keys: KeyGetter | None = None, data_dir: Path | None = None) -> None:
        self._keys = keys
        self.budget = DailyBudget(self.name, DAILY_BUDGET, data_dir)

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        if get_keys(self._keys, self.name, FIELDS) is None:
            return []
        out = []
        for query in cfg.search.queries:
            for location in cfg.search.locations:
                code, _ = split_location(location)
                out.append(
                    Task(
                        self.name,
                        f"adzuna:{query}:{location}",
                        query=query,
                        location=location,
                        limit=cfg.search.max_results_per_query,
                        posted_within_days=cfg.search.posted_within_days,
                        country=code if code in CURRENCY else "",
                    )
                )
        return out

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if not task.country:
            code, _ = split_location(task.location)
            if code:
                raise Unsupported(f"Adzuna has no market for {COUNTRIES[code]}")
            raise Unsupported(
                "Adzuna needs a country in your search locations, e.g. 'London, United Kingdom'"
            )
        keys = get_keys(self._keys, self.name, FIELDS)
        if keys is None:
            return
        _, place = split_location(task.location)
        params: dict[str, Any] = {
            "app_id": keys["app_id"],
            "app_key": keys["app_key"],
            "results_per_page": PAGE_SIZE,
            "what": task.query,
            "sort_by": "date",  # newest first, so a bounded crawl reads what is new
            "max_days_old": task.posted_within_days,
            "content-type": "application/json",
        }
        if place:
            params["where"] = place
        seen = start_page * PAGE_SIZE
        for page in range(start_page + 1, MAX_PAGES + 1):
            if not self.budget.take():
                logger.info("adzuna: the daily budget of {} calls is used up", DAILY_BUDGET)
                return
            data = await http.get_json(f"{URL}/{task.country}/search/{page}", params=params)
            results = data.get("results") or []
            if not results:
                return
            yield [s for r in results if (s := parse_job(r, task.country))]
            seen += len(results)
            if len(results) < PAGE_SIZE or seen >= task.limit:
                return
