"""Getro-powered job boards (`<label>.getro.com`), the platform VC and accelerator portfolios use to
publish their companies' openings. Each posting names its own employer and links to the employer's
own ATS. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import mode
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

SEARCH = "https://api.getro.com/api/v2/collections/{}/search/jobs"
PAGE = 100
JOB_URL = "https://{label}.getro.com/companies/{org}/jobs/{slug}"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _next_data(html: str) -> dict[str, Any]:
    m = _NEXT_DATA.search(html)
    return json.loads(m[1]) if m else {}


class Getro(Source):
    """The board is the label in `<label>.getro.com`."""

    name = "getro"
    kind = "ats"
    # The search API wants the numeric network id, which the board's home page states.
    url_patterns = (
        re.compile(r"(?<![\w.-])(?!(?:www|api|app|help|support)\.)([\w-]+)\.getro\.com", re.I),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        home = await http.get(f"https://{task.board}.getro.com/")
        home.raise_for_status()
        network = ((_next_data(home.text).get("props") or {}).get("pageProps") or {}).get("network")
        if not (network and network.get("id")):
            raise ValueError(f"getro: no network id on {task.board}.getro.com")
        label = network.get("label") or task.board
        for page in range(start_page, 1000):
            data = await http.post_json(
                SEARCH.format(network["id"]), {"hits_per_page": PAGE, "page": page}
            )
            results = data.get("results") or {}
            rows = results.get("jobs") or []
            if not rows:
                return
            if stubs := [s for r in rows if (s := self.stub(r, label))]:
                yield stubs
            if (page + 1) * PAGE >= results.get("count", 0):
                return

    @staticmethod
    def stub(p: dict[str, Any], label: str) -> JobStub | None:
        org = p.get("organization") or {}
        if not (p.get("id") and p.get("slug") and p.get("url") and org.get("name")):
            return None
        locations = list(dict.fromkeys(p.get("locations") or []))
        place = "; ".join(locations)
        # The Getro page (not the employer's link) is the stub url: its slug carries the job id and
        # fetch_details reads the description from it.
        url = JOB_URL.format(label=label, org=org.get("slug") or "-", slug=p["slug"])
        created = p.get("created_at")
        return JobStub(
            source="getro",
            url=url,
            title=(p.get("title") or "").strip(),
            company=org["name"].strip(),
            location=place,
            posted_at=from_epoch_ms(created * 1000) if created else None,
            ats="getro",
            apply_url=p["url"],
            remote=mode((p.get("work_mode") or "").replace("_", "-")) or remote_from_text(place),
            extra={"board": label, "id": p["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        resp = await http.get(stub.url)
        resp.raise_for_status()
        state = ((_next_data(resp.text).get("props") or {}).get("pageProps") or {}).get(
            "initialState"
        )
        job = (((state or {}).get("jobs") or {}).get("currentJob")) or {}
        return stub.model_copy(update={"description": strip_html(job.get("description") or "")})
