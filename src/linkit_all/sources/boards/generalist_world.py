"""Generalist World (generalist.world/jobs/), a curated board of generalist and operator roles
(chief of staff, founder's associate). One server-rendered page lists every posting as a card;
the card's teaser is the description. No date and no employer link at list level.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import absolute, get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import feed_task

LIST = "https://generalist.world/jobs/"
_SLUG = re.compile(r"^https://(?:www\.)?generalist\.world/jobs/([A-Za-z0-9][\w.~-]*)/?$")


class GeneralistWorld(Source):
    name = "generalist-world"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one page holds the whole board
            return
        html = (await get_page(http, LIST)).text
        if "gw-jobs-section" not in html and "data-jobs-container" not in html:
            raise ValueError("generalist-world: the page has no job list (markup changed?)")
        stubs = self.cards(html)[: task.limit]
        if stubs:
            yield stubs

    def cards(self, html: str) -> list[JobStub]:
        found: dict[str, JobStub] = {}  # the Featured block repeats some cards
        for a in LexborHTMLParser(html).css("a.gw-job-card"):
            url = absolute(a.attributes.get("href"), LIST)
            m = _SLUG.match(url)
            title = node_text(a.css_first(".gw-job-title"))
            company = node_text(a.css_first(".gw-job-company"))
            if not (m and title and company) or url in found:
                continue
            region = (a.attributes.get("data-region") or "").strip().title()
            where = node_text(a.css_first(".gw-location")) or region
            found[url] = JobStub(
                source=self.name,
                url=url,
                title=title,
                company=company,
                location=where,
                description=node_text(a.css_first(".gw-job-description")),
                ats=self.name,
                apply_url=url,
                remote=remote_from_text(where),
                extra={"id": m[1], "salary_text": node_text(a.css_first(".gw-salary"))},
            )
        return list(found.values())
