"""Any job board running the WP Job Manager WordPress plugin, through the plugin's public RSS feed
({host}/?feed=job_feed): employer and place in its own `job_listing:` fields, the full post in
`content:encoded`. 100 items a page (`posts_per_page`), walked with `paged` until a short page.
A WordPress site has no host pattern, so add a board as "wp-job-manager:jobs.example.com".
(Our `wpyoast` plugin reads the same kind of site through a Yoast sitemap, one request per
posting; this feed needs one request per 100.) Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import (
    body_text,
    clean,
    feed_items,
    last_segment,
    name_from_host,
    rfc_date,
)

PAGE = 100
MAX_PAGES = 100


class WpJobManager(Source):
    name = "wp-job-manager"
    kind = "ats"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = urlsplit(task.board if "://" in task.board else f"https://{task.board}").hostname
        if not host:
            raise ValueError(f"wp-job-manager: no host in {task.board!r}")
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = f"https://{host}/?feed=job_feed&posts_per_page={PAGE}" + (
                f"&paged={page}" if page > 1 else ""
            )
            text = (await get_page(http, url)).text
            if "<rss" not in text[:3000].lower():
                raise ValueError(f"wp-job-manager: {host} serves no job feed")
            items = feed_items(text)
            stubs = [s for s in self.parse(items, host, task.board) if s.url not in seen]
            seen.update(s.url for s in stubs)
            if stubs:
                yield stubs
            if len(items) < PAGE or not stubs:
                return

    @staticmethod
    def parse(items: list[dict[str, str]], host: str, board: str) -> list[JobStub]:
        stubs = []
        for item in items:
            link = item.get("link", "").strip()
            title = clean(item.get("title"))
            if not (title and urlsplit(link).hostname == host):
                continue
            where = clean(item.get("location"))
            stubs.append(
                JobStub(
                    source="wp-job-manager",
                    url=link,
                    title=title,
                    company=clean(item.get("company")) or name_from_host(host),
                    location=where,
                    description=body_text(item.get("encoded") or item.get("description", "")),
                    posted_at=rfc_date(item.get("pubDate")),
                    ats="wp-job-manager",
                    apply_url=link,
                    remote=remote_from_text(where, title),
                    extra={"board": board, "id": last_segment(link)},
                )
            )
        return stubs
