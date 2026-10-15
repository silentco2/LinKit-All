"""Wuzzuf (Egypt, Saudi Arabia) through its published sitemaps, as robots.txt allows.

robots.txt disallows search pages (/*?q=) and asks for Crawl-delay: 10, so this reads the
job sitemaps, keeps recent URLs whose slug contains every word of one of your queries, and
fetches those job pages one every 10 s (see SLOW_HOSTS). Each page carries a JobPosting.
"""

import re
from collections.abc import AsyncIterator
from datetime import timedelta

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import norm

SITEMAP = "https://wuzzuf.net/sitemap.xml"
PAGE = 10  # job pages per checkpoint
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_URL = re.compile(r"<url>(.*?)</url>", re.S)
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>")


class Wuzzuf(Source):
    name = "wuzzuf"
    priority = 2

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        if self.name not in cfg.sources.regional or not cfg.search.queries:
            return []
        return [Task(self.name, "wuzzuf:sitemap", query="|".join(cfg.search.queries),
                     posted_within_days=cfg.search.posted_within_days)]  # fmt: skip

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        urls = await self.matching_urls(http, task)
        for page in range(start_page, (len(urls) + PAGE - 1) // PAGE):
            stubs = []
            for url in urls[page * PAGE : (page + 1) * PAGE]:
                resp = await http.get(url)
                if resp.status_code == 404:  # filled since the sitemap was built
                    continue
                resp.raise_for_status()
                stubs += [to_stub(p, self.name, url, "wuzzuf") for p in job_postings(resp.text)[:1]]
            yield stubs

    async def matching_urls(self, http: Http, task: Task) -> list[str]:
        queries = [norm(q).split() for q in task.query.split("|") if q.strip()]
        since = utcnow() - timedelta(days=task.posted_within_days)
        index = (await http.get(SITEMAP)).text
        sitemaps = [u for u in _LOC.findall(index) if re.search(r"-job-\d+\.xml$", u)]
        urls: list[str] = []
        for sitemap in sitemaps:
            for entry in _URL.findall((await http.get(sitemap)).text):
                loc, mod = _LOC.search(entry), _LASTMOD.search(entry)
                if loc is None or (mod and (from_iso(mod.group(1)) or since) < since):
                    continue
                slug = set(loc.group(1).rsplit("/", 1)[-1].lower().split("-"))
                if any(all(word in slug for word in q) for q in queries):
                    urls.append(loc.group(1))
        return sorted(set(urls))  # stable order, so page checkpoints survive a resume
