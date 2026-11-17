"""Yourator (www.yourator.co), a Taiwanese startup and digital job board, through its public
JSON API (page by page until `hasMore` is false). A posting that names the employer's own ATS
page (`thirdPartyUrl`) uses it as its address, tracking parameters removed; otherwise the
Yourator page. The list has no body. Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ats_of, clean, safe_date
from linkit_all.sources.tasks import all_older, feed_task, limited

API = "https://www.yourator.co/api/v4/jobs"
ORIGIN = "https://www.yourator.co"
MAX_PAGES = 500


def without_tracking(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(query)))


class Yourator(Source):
    name = "yourator"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(API, params={"page": page})
            payload = data.get("payload") if isinstance(data, dict) else None
            rows = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(payload, dict) or not isinstance(rows, list):
                raise ValueError("yourator: the response carries no payload.jobs array")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            yield stubs
            if payload.get("hasMore") is not True or all_older(stubs, task):
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        title, company = clean(r.get("name")), clean((r.get("company") or {}).get("brand"))
        path = str(r.get("path") or "").strip()
        own = ORIGIN + path if path.startswith("/") and not path.startswith("//") else ""
        external = str(r.get("thirdPartyUrl") or "").strip()
        url = without_tracking(external) if external.startswith("https://") else own
        if not (title and company and url):
            return None
        where = clean(r.get("location"))
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=where,
            posted_at=safe_date(r.get("lastActiveAt")),
            ats=ats_of(url, self.name),
            apply_url=url,
            remote=remote_from_text(where, title),
            extra={
                "id": str(r.get("id") or path),
                "page": own,
                "salary_text": clean(r.get("salary")),
            },
        )
