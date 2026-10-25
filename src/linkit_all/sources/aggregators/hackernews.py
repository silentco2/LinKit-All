"""Hacker News' monthly "Ask HN: Who is hiring?" threads, read through the public HN Algolia API.
Each top-level comment is one employer's post. Logic adapted from freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ITEM = "https://hn.algolia.com/api/v1/items/{}"
PERMALINK = "https://news.ycombinator.com/item?id={}"
THREADS = 2  # this month's (still filling) and last month's (still live early in the month)
_TITLE = re.compile(r"who is hiring", re.I)  # the account also posts "Who wants to be hired?"
_PARA = re.compile(r"<p\b[^>]*>", re.I)
_HREF = re.compile(r'<a\s[^>]*?href="(https?:[^"]+)"', re.I)  # entity-encoded: https:&#x2F;&#x2F;
_URL = re.compile(r"https?://[^\s)\]}>,]+")
_COMMITMENT = re.compile(
    r"^(full[ -]?time|part[ -]?time|contract(or)?|intern(ship)?s?|permanent|freelance)$", re.I
)
# A first segment that is a ROLE ("Senior Software Engineer, Frontend") has shifted every segment
# by one, so no employer can be read. Both words are needed: "Lead Bank" is a real employer.
_SENIORITY = re.compile(
    r"^(sr|jr|senior|junior|staff|principal|lead|founding|head|director|vp|chief)\b", re.I
)
_ROLE = re.compile(
    r"\b(engineer|engineering|developer|designer|scientist|analyst|architect|manager|programmer"
    r"|devops|sre|researcher)\b",
    re.I,
)


class HackerNews(Source):
    name = "hackernews"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        found = await http.get_json(
            SEARCH, params={"tags": "story,author_whoishiring", "hitsPerPage": 10}
        )
        ids = [h["objectID"] for h in found.get("hits") or [] if _TITLE.search(h.get("title", ""))]
        count = 0
        for i, thread_id in enumerate(ids[:THREADS]):
            if i < start_page:  # one page per thread
                continue
            thread = await http.get_json(ITEM.format(thread_id))
            stubs = [s for c in thread.get("children") or [] if (s := self.stub(c))]
            stubs = stubs[: task.limit - count]
            count += len(stubs)
            if stubs:
                yield stubs
            if count >= task.limit:
                return

    def stub(self, c: dict[str, Any]) -> JobStub | None:
        text = (c.get("text") or "").strip()  # null on a deleted comment
        if not (c.get("id") and text):
            return None
        parts = [" ".join(p.split()) for p in strip_html(_PARA.split(text, 1)[0]).split("|")]
        if len(parts) < 2 or (_SENIORITY.match(parts[0]) and _ROLE.search(parts[0])):
            return None
        company, title = (_URL.sub("", p).strip() for p in parts[:2])
        if not (company and title):
            return None
        location = ""
        for seg in parts[2:]:
            seg = _URL.sub("", seg).strip()
            if seg and not _COMMITMENT.match(seg) and seg[0] not in "$€£":
                location = seg
                break
        url = PERMALINK.format(c["id"])
        link = _HREF.search(text)
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=location,
            description=strip_html(text),
            posted_at=from_iso(c.get("created_at")),
            apply_url=html.unescape(link[1]) if link else url,
            remote=remote_from_text(" ".join(parts[1:])),
            ats=self.name,
            extra={"id": c["id"]},
        )
