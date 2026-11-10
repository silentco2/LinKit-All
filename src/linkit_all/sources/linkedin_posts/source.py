"""LinkedIn hiring posts as a discovery source: Google finds the posts, their public pages give
the text, `extract` turns hiring posts into job stubs. No LinkedIn account is used.

One task per job title (at most MAX_KEYWORDS). Posts older than the window are dropped by the date
in their id before any page is fetched, and by the page's own date after. When Google shows a
check, the source stops for the run and leaves a flag file (`check_flag`) that Needs you shows
until the user marks it solved or a later search gets through.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Literal

from loguru import logger

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.careers import Careers, Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.linkedin_posts.extract import SOURCE, posts_to_stubs
from linkit_all.sources.linkedin_posts.google import (
    PROFILE,
    GoogleBlocked,
    GoogleSearch,
    post_id,
    posted_from_id,
)
from linkit_all.sources.linkedin_posts.post import RawPost, read_post
from linkit_all.sources.posts import PostRules

MAX_KEYWORDS = 5  # each keyword is up to MAX_PAGES Google searches
WINDOW_DAYS = {"day": 1, "week": 7}
BLOCKED = {
    "check": "Google asked for a check. Open Needs you and solve the Google check, then run again",
    "consent": "Google asks you to choose cookie settings. Open Needs you and solve the Google "
    "check, then run again",
}


def profile_path(data_dir: Path) -> Path:
    return data_dir / "browser" / PROFILE  # same place as apply.browser.profile_dir


def check_flag(data_dir: Path) -> Path:
    return data_dir / "browser" / f"{PROFILE}-check"


class LinkedInPosts(Source):
    name = SOURCE
    kind = "board"
    priority = 5  # the same job from its ATS or a job board has better data
    parallel = 1  # one Google search at a time

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self._rules = PostRules()
        self._reader = Careers()  # no provider: one page at a time, no AI
        self._google: GoogleSearch | None = None
        self._stopped: str | None = None  # why later keywords of this run are skipped
        self._seen: set[str] = set()  # post ids already read this run
        self._headless = True

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        src = cfg.sources
        self._rules = PostRules.of(cfg)
        self._headless = cfg.apply.headless  # the one window setting
        return [
            Task(
                self.name,
                f"linkedin_posts:{kw.casefold()}",
                query=kw,
                limit=src.linkedin_max_posts,
                posted_within_days=WINDOW_DAYS[src.linkedin_window],
            )
            for kw in dict.fromkeys(k.strip() for k in cfg.search.queries if k.strip())
        ][:MAX_KEYWORDS]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page:  # one page per keyword: already stored
            return
        if self.data_dir is None:
            raise Unsupported("no data folder for the Google browser profile")
        if self._stopped:
            raise Unsupported(self._stopped)
        if self._google is None:
            self._google = GoogleSearch(profile_path(self.data_dir), self._headless)
        window: Literal["day", "week"] = "day" if task.posted_within_days == 1 else "week"
        try:
            urls = await self._google.post_urls(task.query, window, task.limit)
        except GoogleBlocked as e:
            self._stopped = BLOCKED[e.kind]
            check_flag(self.data_dir).parent.mkdir(parents=True, exist_ok=True)
            check_flag(self.data_dir).touch()
            logger.warning("LinkedIn posts stopped: {}", self._stopped)
            raise Unsupported(self._stopped) from None
        check_flag(self.data_dir).unlink(missing_ok=True)
        posts = await self._read(http, urls, task)
        yield await posts_to_stubs(posts, http, self._reader, self._rules, self.is_known)

    async def _read(self, http: Http, urls: list[str], task: Task) -> list[RawPost]:
        now = utcnow()
        cutoff = now - timedelta(days=task.posted_within_days + 1)  # +1: Google's day is local
        posts = []
        for url in urls:
            found = post_id(url)
            if found is None or found[1] in self._seen:
                continue
            self._seen.add(found[1])
            at = posted_from_id(*found)
            if at is not None and at < cutoff:
                continue
            try:
                resp = await http.get(url)
            except Exception as e:  # one unreadable post must not cost the others
                logger.debug("LinkedIn post {} skipped: {}", url, e)
                continue
            post = (
                read_post(resp.text, url, f"urn:li:{found[0]}:{found[1]}", now)
                if resp.status_code == 200
                else None
            )
            if post is not None and (post.posted_at is None or post.posted_at >= cutoff):
                posts.append(post)
        return posts

    async def aclose(self) -> None:
        if self._google is not None:
            await self._google.close()
            self._google = None
