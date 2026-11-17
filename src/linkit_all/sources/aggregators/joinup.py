"""joinup.ch, a Swiss startup job board. The full board sits behind a search key minted at run
time, so only the newest page, server-rendered into the browse page's `__NEXT_DATA__`, is read:
enough for a periodic search. The list has no body.
Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, next_data, safe_date
from linkit_all.sources.tasks import feed_task

BROWSE = "https://joinup.ch/browse/jobs"
JOB = "https://joinup.ch/job/{}"


def _created(value: Any) -> Any:
    if isinstance(value, int | float):  # a few older records carry an epoch
        return from_epoch_ms(value * 1000 if value < 1e12 else value) if value > 0 else None
    return safe_date(value)


class JoinUp(Source):
    name = "joinup"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = next_data((await get_page(http, BROWSE)).text)
        if data is None:
            raise ValueError("joinup: the browse page has no __NEXT_DATA__")
        try:
            state = data["props"]["pageProps"]["serverState"]["initialResults"]
            hits = state["jobs"]["results"][0]["hits"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("joinup: the page data lists no job hits") from None
        stubs = [s for h in hits if isinstance(h, dict) and (s := self.stub(h))][: task.limit]
        if stubs:
            yield stubs

    def stub(self, h: dict[str, Any]) -> JobStub | None:
        title, company = clean(h.get("title") or h.get("headline")), clean(h.get("startup"))
        slug = str(h.get("slug") or "").strip()
        if not (title and company and slug):
            return None
        loc = h.get("location")
        where = clean(loc.get("name") or loc.get("city") if isinstance(loc, dict) else loc)
        return JobStub(
            source=self.name,
            url=JOB.format(slug),
            title=title,
            company=company,
            location=where,
            posted_at=_created(h.get("created")),
            ats=self.name,
            apply_url=JOB.format(slug),
            remote=remote_from_text(where),
            extra={"id": slug},
        )
