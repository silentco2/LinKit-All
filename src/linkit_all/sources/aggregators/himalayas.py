"""Himalayas (himalayas.app), a remote-jobs aggregator with a public offset-paged API that carries
every body. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import all_older, feed_task
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://himalayas.app/jobs/api"
PAGE = 20  # the API caps the page size here, whatever is asked
_PROMO = re.compile(r"\s*Originally posted on\s+Himalayas\s*$", re.I)  # the site's own trailer


class Himalayas(Source):
    name = "himalayas"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # The API answers 429 after ~150 quick requests; the task limit keeps a run well below it.
        for page in range(start_page, ceil(task.limit / PAGE)):
            data = await http.get_json(API, params={"limit": PAGE, "offset": page * PAGE})
            rows = data.get("jobs") or []
            if not rows:
                return
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            if (page + 1) * PAGE >= data.get("totalCount", 0) or all_older(stubs, task):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company = (p.get("companyName") or "").strip()
        if company.lower() == "name":  # the feed leaves this template word in ~1 in 5 rows
            company = (p.get("companySlug") or "").strip()
        url = (p.get("applicationLink") or p.get("guid") or "").lstrip(":")
        if not (url and company and p.get("title")):
            return None
        return JobStub(
            source=self.name,
            url=url,
            title=p["title"],
            company=company,
            location=", ".join(p.get("locationRestrictions") or []),
            description=_PROMO.sub("", strip_html(p.get("description") or "")),
            posted_at=from_epoch_ms((p.get("pubDate") or 0) * 1000),
            apply_url=url,
            remote="remote",  # the site lists remote jobs only
            ats=self.name,
            extra={"id": p.get("guid") or url},
        )
