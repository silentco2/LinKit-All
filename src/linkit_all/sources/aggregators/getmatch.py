"""getmatch (getmatch.ru), a curated Russian IT job marketplace. The public feed lists offers; the
body and skills come from each offer's own endpoint (`fetch_details`).
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

BASE = "https://getmatch.ru"
LIST = BASE + "/api/offers"
PAGE = 100
_ID = re.compile(r"/vacancies/(\d+)")
_FORMATS: dict[str, Remote] = {"remote": "remote", "hybrid": "hybrid", "office": "onsite"}


def _mode(items: list[dict[str, Any]]) -> Remote | None:
    """The work mode when the locations agree on one (relocation flags are ignored)."""
    modes = {_FORMATS[i["format"]] for i in items if i.get("format") in _FORMATS}
    return modes.pop() if len(modes) == 1 else None


class GetMatch(Source):
    name = "getmatch"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page, ceil(task.limit / PAGE)):
            data = await http.get_json(LIST, params={"offset": page * PAGE, "limit": PAGE})
            rows = data.get("offers") or []
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            total = (data.get("meta") or {}).get("total") or 0
            if not rows or (total and (page + 1) * PAGE >= total):
                return

    def stub(self, o: dict[str, Any]) -> JobStub | None:
        company = (o.get("company") or {}).get("name")
        if not o.get("id") or not o.get("position") or not o.get("url") or not company:
            return None
        items = o.get("location_items") or []
        url = BASE + o["url"]
        return JobStub(
            source=self.name,
            url=url,
            title=o["position"].strip(),
            company=company,
            location=", ".join(dict.fromkeys(i["label"] for i in items if i.get("label"))),
            posted_at=from_iso(o.get("published_at")),  # zone-less
            apply_url=url,
            remote=_mode(items),
            extra={"id": o["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if not m:
            return stub
        d = await http.get_json(f"{LIST}/{m[1]}")
        text = strip_html(d.get("description") or "")
        skills = [s["name"] for s in d.get("skills_objects") or [] if s.get("name")]
        if skills:
            text = f"{text}\n\nSkills: {', '.join(skills)}".strip()
        return stub.model_copy(update={"description": text})
