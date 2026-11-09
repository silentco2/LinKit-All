"""Jobs from public Telegram channels, read through their web preview (https://t.me/s/<name>).

No login, no Bot API: the preview shows the latest ~20 posts of a public channel, older ones
via `?before=<id>`. A post is kept when it holds a hiring word (English, Russian, Ukrainian,
Spanish, Arabic) or links to a known ATS. No AI here: a post linking to an ATS becomes a stub
pointing at that ATS; any other post is read by script (`posts`): an email makes it an email
application, a link goes to the careers scraper, and a post with neither is dropped. The stub's
url is the post (https://t.me/<channel>/<id>), the dedupe key. Posts older than MAX_AGE_DAYS are
skipped.
Idea and word lists after freehire (MIT, https://github.com/strelov1/freehire), re-implemented.
"""

# ruff: noqa: RUF001, RUF003  (Cyrillic and Arabic hiring words are the point here)
import asyncio
import re
import time
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.careers import Careers, Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.posts import PostJob, PostRules, find_links, fold, is_seeker, post_stub

PREVIEW = "https://t.me/s/{channel}"
MAX_AGE_DAYS = 45
MAX_PAGES = 5  # preview pages per channel and run (~20 posts each)
DELAY = 2.0  # seconds between two preview fetches
DESCRIPTION = 4000  # characters of a post kept as the job description

_MARKERS = re.compile(
    fold(
        "|".join(
            (
                # Russian
                r"ваканси|ищем|ищут|требуетс|нужен|нужна|нужны|наним|набираем|зарплат|оклад|"
                r"на руки|стажировк|резюме",
                # English
                r"hiring|vacanc|looking for|join (?:our|the) team|apply|salary|needed\b|"
                r"send (?:us )?(?:your |an? )?(?:cv|resume)",
                # Ukrainian ("шукає" covers "шукаємо", not the job-seeker "шукаю")
                r"вакансі|шукає|запрошуємо|стажуванн|досвід роботи",
                # Spanish: the labelled field, not the bare noun (the noun is ordinary prose)
                r"empresa\s*:",
                # Arabic
                r"مطلوب|وظيفة|وظائف|وظايف|فرصة عمل|فرص عمل|نبحث عن|نطلب|توظيف|شاغر|تعيين|راتب|"
                r"دوام كامل|دوام جزئي|عن بعد|تعلن عن",
                # salary amounts: "250 000 руб", "$120k", "120k-200k"
                r"\d[\d\s]{2,}\s*(?:руб|₽|€|\$)|[$€£]\s?\d+\s?k|\d+\s?k\s*[-–—]\s*\$?\d+\s?k",
            )
        )
    )
)


def looks_like_vacancy(text: str) -> bool:
    return _MARKERS.search(fold(text)) is not None


@dataclass(frozen=True)
class Post:
    id: int
    posted_at: datetime  # naive UTC
    text: str
    links: tuple[str, ...]


def _text(node: LexborNode) -> str:
    html = re.sub(r"<br\s*/?>", "\n", node.html or "")
    lines = (" ".join(line.split()) for line in LexborHTMLParser(html).text().splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_posts(html: str, channel: str) -> list[Post]:
    """The posts of one preview page, oldest first. Photo-only or undated posts are left out."""
    posts = []
    for msg in LexborHTMLParser(html).css("div.tgme_widget_message[data-post]"):
        owner, _, num = (msg.attributes.get("data-post") or "").partition("/")
        stamp, body = msg.css_first("time[datetime]"), msg.css_first("div.tgme_widget_message_text")
        if owner.lower() != channel.lower() or not num.isdigit() or not stamp or not body:
            continue
        try:
            when = from_iso(stamp.attributes.get("datetime"))
        except ValueError:
            continue
        links = tuple(
            href
            for a in body.css("a[href]")
            if (href := (a.attributes.get("href") or "").strip()).startswith(
                ("http://", "https://")
            )
        )
        if when and (text := _text(body)):
            posts.append(Post(int(num), when, text, links))
    return sorted(posts, key=lambda p: p.id)


def _ats_link(post: Post) -> tuple[str, str, str] | None:
    """(ats, board slug, url) of the first link in the post that a known ATS hosts."""
    for url in post.links:
        if (found := detect(url)) is not None:
            return found[0], found[1], url
    return None


class Telegram(Source):
    name = "telegram"
    kind = "telegram"
    priority = 5  # the same job from its ATS or a job board has better data
    parallel = 1  # one channel at a time, DELAY apart

    def __init__(self) -> None:
        self._last_fetch = 0.0
        self._rules = PostRules()
        self._reader = Careers()  # no provider: one page at a time, no AI

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        self._rules = PostRules.of(cfg)
        return [
            Task(self.name, f"telegram:{c.lower()}", board=c, posted_within_days=MAX_AGE_DAYS)
            for c in cfg.sources.telegram_channels
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        channel, cutoff = task.board, utcnow() - timedelta(days=MAX_AGE_DAYS)
        await http.allowed(PREVIEW.format(channel=channel))
        before = 0
        for page in range(MAX_PAGES):
            posts = await self._preview(http, channel, before)
            if not posts:
                if page == 0:
                    raise Unsupported("no public posts (not a channel, or its preview is off)")
                return
            before = posts[0].id
            if page >= start_page:  # a resumed run walks the earlier pages again, for `before`
                yield await self._stubs(http, channel, [p for p in posts if p.posted_at >= cutoff])
            if posts[0].posted_at < cutoff:  # the oldest post of this page is already too old
                return

    async def _preview(self, http: Http, channel: str, before: int) -> list[Post]:
        if (wait := self._last_fetch + DELAY - time.monotonic()) > 0:
            await asyncio.sleep(wait)
        url = PREVIEW.format(channel=channel) + (f"?before={before}" if before else "")
        try:
            resp = await http.get(url)
        finally:
            self._last_fetch = time.monotonic()
        resp.raise_for_status()
        return parse_posts(resp.text, channel)

    async def _stubs(self, http: Http, channel: str, posts: list[Post]) -> list[JobStub]:
        links = {p.id: tuple(dict.fromkeys((*p.links, *find_links(p.text)))) for p in posts}
        counts = Counter(u for found in links.values() for u in found)

        async def one(post: Post) -> JobStub | None:
            if link := _ats_link(post):
                return self._linked(channel, post, *link)
            if is_seeker(post.text) or not looks_like_vacancy(post.text):
                return None
            url = f"https://t.me/{channel}/{post.id}"
            own = tuple(u for u in links[post.id] if counts[u] == 1)  # shared = a channel footer
            job = PostJob(self.name, url, post.text, own, post.posted_at,
                          {"channel": channel, "post": post.id})  # fmt: skip
            return await post_stub(http, self._reader, job, self._rules,
                                   fetch=not self.is_known(url))  # fmt: skip

        return [s for s in await asyncio.gather(*(one(p) for p in posts)) if s]

    def _linked(self, channel: str, post: Post, ats: str, board: str, link: str) -> JobStub:
        first = post.text.splitlines()[0]
        return JobStub(
            source=self.name,
            url=f"https://t.me/{channel}/{post.id}",
            title=first[:120],
            company=board.split("/")[0].replace("-", " ").replace("_", " ").title(),
            description=post.text[:DESCRIPTION],
            posted_at=post.posted_at,
            ats=ats,
            apply_url=link,
            remote=remote_from_text(first),
            extra={"channel": channel, "post": post.id},
        )
