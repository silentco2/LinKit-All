"""top.co, the careers board of the TOP (TON Open Platform) ecosystem; a Next.js page lists the
vacancies in its inline RSC data and each posting's own endpoint has the body.
Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

CAREERS = "https://top.co/careers"
JOB_URL = CAREERS + "/{}"
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_ID = re.compile(r"/careers/(\w+)")
_DECODER = json.JSONDecoder()


def flight(page: str) -> str:
    """The page's Next.js flight stream: its `__next_f.push([1,"..."])` chunks, decoded."""
    return "".join(json.loads(m[1]) for m in _PUSH.finditer(page))


def value_after(text: str, key: str) -> Any:
    """The JSON value following the first `key` (such as `"body":`) in `text`; None when the key
    is absent or no JSON value follows."""
    at = text.find(key)
    if at < 0:
        return None
    try:
        return _DECODER.raw_decode(text, at + len(key))[0]
    except ValueError:
        return None


class TopCo(Source):
    name = "topco"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page:  # the whole board is one page
            return
        await http.allowed(CAREERS)
        resp = await http.get(CAREERS)
        resp.raise_for_status()
        vacancies = value_after(flight(resp.text), '"vacancies":')
        if not isinstance(vacancies, list):
            raise ValueError("top.co careers page carries no vacancies list")
        stubs = []
        for v in vacancies:
            company = (v.get("company") or {}).get("name")
            if v.get("id") and v.get("position") and company:
                url = JOB_URL.format(v["id"])
                stubs.append(
                    JobStub(
                        source=self.name,
                        url=url,
                        title=v["position"].strip(),
                        company=company,
                        apply_url=url,
                        remote="remote",  # the ecosystem's roles are global and remote
                        extra={"id": v["id"]},
                    )
                )
        if stubs:
            yield stubs[: task.limit]

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _ID.search(stub.url):
            return stub
        # `RSC: 1` is the header Next.js itself sends for page data; without it the page is HTML.
        resp = await http.get(stub.url, headers={"RSC": "1"})
        if resp.status_code != 200:
            return stub
        parts = []
        for key in ("body", "requirements", "conditions"):
            value = value_after(resp.text, f'"{key}":')
            if isinstance(value, str) and not value.startswith("$"):  # "$undefined" placeholders
                parts.append(strip_html(value))
        return stub.model_copy(update={"description": "\n\n".join(p for p in parts if p)})
