"""WhatJobs publisher feed (api.whatjobs.com), a job network with one publisher account per
country. Setup → API keys takes the IDs as "gb=123, us=456"; the country in each search location
picks the account. Links are the network's tracked landing pages. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.keys import (
    COUNTRIES,
    KeyGetter,
    get_keys,
    parse_ids,
    split_location,
)
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

URL = "https://api.whatjobs.com/api/v1/jobs.json"
PAGE_SIZE = 50  # the maximum; larger values are clamped
MAX_PAGES = 40  # the feed stops serving results about 2,000 pages deep
MIN_RELEVANT = 0.5  # the keyword ranks rather than filters, and pads thin results with noise
# A crawl is not a visitor, so the mandatory user_ip is a placeholder, never a real address.
CRAWL_IP = "0.0.0.0"  # noqa: S104
_TRACKED_ID = re.compile(r"pub_api__cpl__(\d+)__\d+")
_RESELLER_MARK = re.compile(r"\s*#J-\d+-Ljbffr\s*$")
_GENERIC = {"developer", "engineer", "programmer", "dev", "specialist", "architect"}


def publisher_ids(keys: dict[str, str]) -> dict[str, str]:
    ids = parse_ids(keys.get("publisher_ids", ""))
    return {("gb" if code == "uk" else code): ident for code, ident in ids.items()}


def parse_job(item: dict[str, Any], country: str) -> JobStub | None:
    url = item.get("url") or ""
    m = _TRACKED_ID.search(url)
    if not m or not item.get("title"):  # no id = no way to dedupe it
        return None
    city = (item.get("location") or "").strip()
    place = COUNTRIES[country]
    return JobStub(
        source="whatjobs",
        url=url,
        title=" ".join(str(item["title"]).split()),
        company=(item.get("company") or "").strip(),
        location=f"{city}, {place}" if city else place,
        # `snippet` holds the full description despite its name.
        description=_RESELLER_MARK.sub("", strip_html(item.get("snippet") or "")),
        apply_url=url,
        remote=remote_from_text(item.get("title"), city),
        ats="whatjobs",
        extra={"id": m.group(1), "country": country},
    )


def _terms(query: str) -> list[str]:
    return [w for w in query.lower().split() if w not in _GENERIC]


class WhatJobs(Source):
    name = "whatjobs"
    kind = "aggregator"
    parallel = 2  # more in flight and the feed answers 429

    def __init__(self, keys: KeyGetter | None = None) -> None:
        self._keys = keys

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        if get_keys(self._keys, self.name, ("publisher_ids",)) is None:
            return []
        return [
            Task(
                self.name,
                f"whatjobs:{query}:{location}",
                query=query,
                location=location,
                limit=cfg.search.max_results_per_query,
                posted_within_days=cfg.search.posted_within_days,
                country=split_location(location)[0] or "",
            )
            for query in cfg.search.queries
            for location in cfg.search.locations
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        keys = get_keys(self._keys, self.name, ("publisher_ids",))
        if keys is None:
            return
        ids = publisher_ids(keys)
        if not task.country:
            raise Unsupported(
                "WhatJobs needs a country in your search locations, e.g. 'Cairo, Egypt'"
            )
        if task.country not in ids:
            raise Unsupported(
                f"no WhatJobs publisher ID for {COUNTRIES[task.country]} in Setup → API keys"
            )
        terms = _terms(task.query)
        seen: set[str] = set()
        total = 0
        for page in range(start_page + 1, MAX_PAGES + 1):
            params = {
                "publisher": ids[task.country],
                "user_ip": CRAWL_IP,
                "keyword": task.query,
                "limit": PAGE_SIZE,
                "page": page,
            }
            data = (await http.get_json(URL, params=params)).get("data") or []
            if not data:
                return
            usable = [s for p in data if (s := parse_job(p, task.country))]
            if not usable:
                raise RuntimeError(f"WhatJobs page {page} has no tracked job ids; format changed?")
            named = [
                s for s in usable if all(t in f"{s.title} {s.description}".lower() for t in terms)
            ]
            fresh = [s for s in named if s.extra["id"] not in seen]  # pages can repeat a job
            seen.update(s.extra["id"] for s in fresh)
            yield fresh
            total += len(fresh)
            # Relevance falls off a cliff rather than tapering; past it every page is padding.
            if (terms and len(named) < MIN_RELEVANT * len(usable)) or total >= task.limit:
                return
