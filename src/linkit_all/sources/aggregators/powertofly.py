"""PowerToFly (powertofly.com), a diversity-focused job board. The public jobs API carries every
body inline and pages by number; applications are hosted on powertofly.com itself.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://powertofly.com/api/v1/jobs/"
JOB_URL = "https://powertofly.com/jobs/detail/{}"
PAGE = 50
_MODES: dict[str, Remote] = {
    "remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite",
}  # fmt: skip


class PowerToFly(Source):
    name = "powertofly"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, ceil(task.limit / PAGE) + 1):
            data = await http.get_json(API, params={"page": page})
            rows = data.get("data") or []
            if stubs := [s for r in rows if (s := self.stub(r))]:
                yield stubs
            if not rows or not (data.get("meta") or {}).get("next_page"):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company = ((p.get("company") or {}).get("name") or "").strip()
        if not p.get("id") or not company or not p.get("title"):
            return None
        # "location" is the work arrangement (Onsite/Hybrid/Remote), not geography
        place = [(p.get(k) or {}).get("title") or "" for k in ("city", "state", "country")]
        location = ", ".join(x for x in place if x) or ", ".join(p.get("location_regions") or [])
        url = JOB_URL.format(p["id"])
        return JobStub(
            source=self.name,
            url=url,
            title=p["title"].strip(),
            company=company,
            location=location,
            description=strip_html(p.get("description") or ""),
            ats=self.name,
            apply_url=url,
            remote=_MODES.get((p.get("location") or "").strip().lower()),
            extra={"id": p["id"]},
        )
