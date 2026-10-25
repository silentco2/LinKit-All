"""Jobspresso (jobspresso.co), a curated remote-jobs board on WordPress Job Manager: its RSS feed
carries employer, location and the full body. Logic adapted from freehire (MIT)."""

import html
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import body_text, feed_items, rfc_date
from linkit_all.sources.tasks import feed_task

FEED = "https://jobspresso.co/feed/?post_type=job_listing"


def _employer(creator: str) -> tuple[str, str]:
    """(company, location) from dc:creator, which reads "Company<br>(pin) Location"."""
    company, _, rest = creator.partition("<br>")
    return html.unescape(company).strip(), html.unescape(rest).strip().removeprefix("⚲").strip()


def _post_id(guid: str, link: str) -> str:
    """The numeric post id of the guid's `p=` parameter, else the link's last segment."""
    ids = parse_qs(urlsplit(html.unescape(guid).strip()).query).get("p")
    return ids[0].strip() if ids and ids[0].strip() else link.strip().rstrip("/").rpartition("/")[2]


class Jobspresso(Source):
    name = "jobspresso"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is not paged
            return
        stubs = []
        for item in feed_items((await get_page(http, FEED)).text):
            company, location = _employer(item.get("creator", ""))
            link = item.get("link", "").strip()
            post_id = _post_id(item.get("guid", ""), link)
            if not (post_id and company and link):
                continue
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=html.unescape(item.get("title", "")).strip(),
                    company=company,
                    location=location,
                    description=body_text(item.get("encoded") or item.get("description", "")),
                    posted_at=rfc_date(item.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote="remote",
                    extra={"id": post_id},
                )
            )
        yield stubs[: task.limit]
