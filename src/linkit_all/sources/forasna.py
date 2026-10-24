"""Forasna (Egypt, Saudi Arabia; mostly Arabic) via its published sitemaps, as robots.txt allows.

robots.txt allows everything except search/filter URLs and asks for Crawl-delay: 10, so this
reads the numbered sitemaps, keeps recent /job/p/ URLs whose slug contains every word of one of
your queries, and fetches those pages one every 10 s (see SLOW_HOSTS). Each page carries a
JobPosting. Slugs are mostly Arabic: use Arabic query words (e.g. "محاسب") to match Arabic
titles; English words only match titles written in English.
"""

import re
from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import unquote, urlsplit

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import norm

SITEMAP = "https://forasna.com/sitemap.xml"
PAGE = 10  # job pages per checkpoint
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_URL = re.compile(r"<url>(.*?)</url>", re.S)
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>")
_JOB_SITEMAP = re.compile(r"/sitemap\d+\.xml$")  # not /careers/ (their own blog)


class Forasna(Source):
    name = "forasna"
    kind = "regional"
    priority = 2

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        if self.name not in cfg.sources.regional or not cfg.search.queries:
            return []
        return [Task(self.name, "forasna:sitemap", query="|".join(cfg.search.queries),
                     posted_within_days=cfg.search.posted_within_days)]  # fmt: skip

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        urls = await self.matching_urls(http, task)
        for page in range(start_page, (len(urls) + PAGE - 1) // PAGE):
            stubs = []
            for url in urls[page * PAGE : (page + 1) * PAGE]:
                resp = await http.get(url)
                if resp.status_code in (404, 410):  # filled or expired since the sitemap
                    continue
                resp.raise_for_status()
                postings = job_postings(resp.text)[:1]
                stubs += [to_stub(p, self.name, url, "forasna") for p in postings]
            yield stubs

    async def matching_urls(self, http: Http, task: Task) -> list[str]:
        queries = [norm(q).split() for q in task.query.split("|") if q.strip()]
        since = utcnow() - timedelta(days=task.posted_within_days)
        urls: set[str] = set()
        # ponytail: the index does not say which sitemap lists jobs (today only one does; the
        # others are category and company pages, ~10 MB each), so all are read: ~1 request per
        # 10 s. Remember the job sitemap's name between runs if this gets slow.
        for sitemap in await self._sitemaps(http):
            if not await _allowed(http, sitemap):
                continue
            text = (await http.get(sitemap)).text
            for entry in _URL.findall(text):
                loc, mod = _LOC.search(entry), _LASTMOD.search(entry)
                if loc is None or "/job/p/" not in loc.group(1):
                    continue
                if mod and (from_iso(mod.group(1)) or since) < since:
                    continue
                slug = norm(unquote(urlsplit(loc.group(1)).path.rsplit("/", 1)[-1])).split()
                if any(all(word in slug for word in q) for q in queries):
                    urls.add(loc.group(1))
        return [u for u in sorted(urls) if await _allowed(http, u)]  # stable page order

    async def _sitemaps(self, http: Http) -> list[str]:
        if not await _allowed(http, SITEMAP):
            return []
        index = (await http.get(SITEMAP)).text
        return [u for u in _LOC.findall(index) if _JOB_SITEMAP.search(u)]


async def _allowed(http: Http, url: str) -> bool:
    # Product choice, not a robots rule: sitemaps and job pages never need a query string.
    return not urlsplit(url).query and await http.allowed(url)
