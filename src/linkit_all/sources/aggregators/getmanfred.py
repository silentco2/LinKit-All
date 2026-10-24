"""Get Manfred (getmanfred.com), a curated Spanish developer job marketplace. The public list has
no body, so `fetch_details` reads each offer's own endpoint.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.http import Http

LIST = "https://www.getmanfred.com/api/v2/public/offers"
JOB_URL = "https://www.getmanfred.com/ofertas-empleo/{}/{}"
PAGE = 100
_ID = re.compile(r"/ofertas-empleo/(\d+)")


def _mode(percent: int | None) -> Remote:
    return "remote" if (percent or 0) >= 100 else "hybrid" if (percent or 0) > 0 else "onsite"


class GetManfred(Source):
    name = "getmanfred"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        offers = await http.get_json(LIST, params={"lang": "ES"})
        active = [o for o in offers if str(o.get("status", "")).upper() == "ACTIVE"][: task.limit]
        for i in range(start_page * PAGE, len(active), PAGE):
            if stubs := [s for o in active[i : i + PAGE] if (s := self.stub(o))]:
                yield stubs

    def stub(self, o: dict[str, Any]) -> JobStub | None:
        company = (o.get("company") or {}).get("name")
        if not o.get("id") or not o.get("position") or not company:
            return None
        url = JOB_URL.format(o["id"], o.get("slug") or "")
        return JobStub(
            source=self.name,
            url=url,
            title=o["position"].strip(),
            company=company,
            location="; ".join(o.get("locations") or []),
            posted_at=from_iso(o.get("updatedAt")),
            apply_url=url,
            remote=_mode(o.get("remotePercentage")),
            extra={"id": o["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if not m:
            return stub
        d = await http.get_json(f"{LIST}/{m[1]}", params={"lang": "ES"})
        parts = [d.get("introduction"), d.get("whatWillYouDo")]
        duties = [r for r in d.get("responsibilities") or [] if r and r.strip()]
        parts.append("\n".join(f"- {r}" for r in duties))
        parts += [d.get("howWillYouDoIt"), d.get("whatTheyAskFor"), d.get("whatOffering")]
        techs = [t["name"] for t in d.get("techs") or [] if t.get("name")]
        if techs:
            parts.append(f"Tech stack: {', '.join(techs)}")
        text = "\n\n".join(p.strip() for p in parts if p and p.strip())  # Markdown reads as is
        return stub.model_copy(update={"description": text})
