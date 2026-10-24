"""Jobs from public Telegram channels, read through their web preview (https://t.me/s/<name>).

No login, no Bot API: the preview shows the latest ~20 posts of a public channel, older ones
via `?before=<id>`. A post is kept when it holds a hiring word (English, Russian, Ukrainian,
Spanish, Arabic) or links to a known ATS. A post linking to an ATS becomes a stub pointing at
that ATS (no AI); the others go to the AI in batches of AI_BATCH posts per call, when a provider
is available. The stub's url is the post (https://t.me/<channel>/<id>), which is the dedupe key;
a second job in the same post gets `?job=2`. Posts older than MAX_AGE_DAYS are skipped.
Idea and word lists after freehire (MIT, https://github.com/strelov1/freehire), re-implemented.
"""

# ruff: noqa: RUF001, RUF002, RUF003  (Cyrillic and Arabic hiring words are the point here)
import asyncio
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, render
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http

PREVIEW = "https://t.me/s/{channel}"
MAX_AGE_DAYS = 45
MAX_PAGES = 5  # preview pages per channel and run (~20 posts each)
DELAY = 2.0  # seconds between two preview fetches
AI_BATCH = 10  # posts per AI call
EXCERPT = 1500  # characters of each post sent to the model
DESCRIPTION = 4000  # characters of a post kept as the job description

_MARKS = re.compile("[ؐ-ًؚ-ٰٟـ]")  # Arabic diacritics, tatweel
_LETTERS = str.maketrans("أإآٱةىئؤ", "ااااهييو")


def fold(text: str) -> str:
    """Lower case; Arabic alef forms -> ا, ة -> ه, ى/ئ -> ي, ؤ -> و; diacritics and tatweel gone."""
    return _MARKS.sub("", text.translate(_LETTERS)).lower()


_MARKERS = re.compile(
    fold(
        "|".join(
            (
                # Russian
                r"ваканси|ищем|ищут|требуетс|нужен|нужна|нужны|наним|набираем|зарплат|оклад|"
                r"на руки|стажировк|резюме",
                # English
                r"hiring|vacanc|looking for|join (?:our|the) team|apply|salary",
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


class ExtractedJob(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    remote: Literal["remote", "hybrid", "onsite"] | None = None
    description: str = ""


class ExtractedPost(BaseModel):
    id: int  # our number in the batch; replies with other ids are ignored
    jobs: list[ExtractedJob] = []


class ExtractedPosts(BaseModel):
    posts: list[ExtractedPost]


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

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider
        self._last_fetch = 0.0

    def tasks(self, cfg: SearchConfig) -> list[Task]:
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
                yield await self._stubs(channel, [p for p in posts if p.posted_at >= cutoff])
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

    async def _stubs(self, channel: str, posts: list[Post]) -> list[JobStub]:
        stubs: list[JobStub] = []
        ask: list[Post] = []
        for post in posts:
            if link := _ats_link(post):
                stubs.append(self._linked(channel, post, *link))
            elif looks_like_vacancy(post.text):
                ask.append(post)
        for start in range(0, len(ask), AI_BATCH):
            stubs += await self._extract(channel, ask[start : start + AI_BATCH])
        return stubs

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

    async def _extract(self, channel: str, posts: list[Post]) -> list[JobStub]:
        """One AI call for a batch of posts; ids are ours, any other id in the reply is dropped.
        Without a provider nothing is guessed: such posts yield no job."""
        if self.provider is None:
            return []
        sent = [{"id": n, "text": p.text[:EXCERPT]} for n, p in enumerate(posts)]
        try:
            result = await self.provider.complete(
                render("extract_telegram.j2", posts=sent), ExtractedPosts
            )
        except UsageLimitError:
            raise  # pause the run cleanly instead of silently degrading
        except ProviderError:
            return []
        stubs: list[JobStub] = []
        seen: set[int] = set()
        for found in result.posts:
            if not 0 <= found.id < len(posts) or found.id in seen:
                continue
            seen.add(found.id)
            post = posts[found.id]
            post_url = f"https://t.me/{channel}/{post.id}"
            jobs = [j for j in found.jobs if j.title.strip()]
            for n, job in enumerate(jobs, 1):
                # The post itself is the safest description. A post with several jobs covers
                # all of them, so those keep the model's own summary of theirs.
                text = post.text if len(jobs) == 1 else job.description or post.text
                stubs.append(
                    JobStub(
                        source=self.name,
                        url=post_url + (f"?job={n}" if n > 1 else ""),
                        title=job.title.strip(),
                        company=job.company.strip() or "Unknown",
                        location=job.location.strip(),
                        description=text[:DESCRIPTION],
                        posted_at=post.posted_at,
                        apply_url=post_url,
                        remote=job.remote or remote_from_text(job.title, job.location),
                        extra={"channel": channel, "post": post.id},
                    )
                )
        return stubs
