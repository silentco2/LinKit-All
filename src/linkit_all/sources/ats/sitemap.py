"""Jobs from an employer's own sitemap.xml, for career sites with no readable ATS. Add one as
"sitemap:https://careers.example.com/sitemap.xml". The sitemap (or the sitemaps an index lists,
one level down) is read; addresses on the same host whose path looks like a posting are kept,
newest <lastmod> first, each titled from its last path part. `fetch_details` reads the page's
schema.org JobPosting for the real title, place, date and body.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, page_text, sitemap_by_date, sitemap_locs
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean, last_segment, name_from_host, safe_date
from linkit_all.sources.text import html_to_text

PAGE = 100  # postings per yielded page
MAX_URLS = 50_000  # the sitemap protocol's own ceiling per file
MAX_SITEMAPS = 50
# ponytail: a path heuristic instead of a per-site pattern; a site with other posting paths
# needs its own plugin (or a pattern setting) if this misses it.
_JOBLIKE = re.compile(
    r"/(?:jobs?|careers?|positions?|vacanc(?:y|ies)|openings?|stellen(?:angebote?)?|"
    r"offres?|empleos?|vagas?|vacatures?)/[^/?#]+",
    re.I,
)
_ID = re.compile(r"(\d{3,})(?!.*\d{3,})")


def slug_title(url: str) -> str:
    """ "/jobs/123/senior-data-engineer" -> "Senior Data Engineer"; ids and ".html" dropped."""
    slug = re.sub(r"\.html?$", "", last_segment(url))
    words = [w for w in re.split(r"[-_]+", slug) if w and not w.isdigit()]
    return " ".join(w[:1].upper() + w[1:] for w in words)


class Sitemap(Source):
    name = "sitemap"
    kind = "ats"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        url = task.board if "://" in task.board else f"https://{task.board}"
        host = urlsplit(url).hostname or ""
        urls = await self.posting_urls(http, url, host)
        company = name_from_host(host)
        for i in range(start_page * PAGE, len(urls), PAGE):
            yield [s for u in urls[i : i + PAGE] if (s := self.stub(u, task.board, company))]

    async def posting_urls(self, http: Http, url: str, host: str) -> list[str]:
        def keep(u: str) -> bool:
            return urlsplit(u).hostname == host and bool(_JOBLIKE.search(urlsplit(u).path))

        xml = (await get_page(http, url)).text
        if "<sitemapindex" not in xml[:2000].lower():
            return sitemap_by_date(xml, keep)[:MAX_URLS]
        found: list[str] = []
        children = [c for c in sitemap_locs(xml) if urlsplit(c).hostname == host]
        for child in children[:MAX_SITEMAPS]:
            found += sitemap_by_date((await get_page(http, child)).text, keep)
        return list(dict.fromkeys(found))[:MAX_URLS]

    @staticmethod
    def stub(url: str, board: str, company: str) -> JobStub | None:
        title = slug_title(url)
        if not title:
            return None
        m = _ID.search(urlsplit(url).path)
        return JobStub(
            source="sitemap",
            url=url,
            title=title,
            company=company,
            ats="sitemap",
            apply_url=url,
            extra={"board": board, "id": m[1] if m else last_segment(url)},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        if not found:
            return stub
        p = found[0]
        places = p.get("jobLocation")
        places = places if isinstance(places, list) else [places]
        where = "; ".join(
            ", ".join(
                x
                for k in ("addressLocality", "addressRegion", "addressCountry")
                if (
                    x := clean(
                        (pl.get("address") or {}).get(k)
                        if isinstance(pl.get("address"), dict)
                        else ""
                    )
                )
            )
            for pl in places
            if isinstance(pl, dict)
        )
        org = p.get("hiringOrganization")
        update = {
            "title": clean(p.get("title")),
            "company": clean(org.get("name") if isinstance(org, dict) else org),
            "location": where,
            "posted_at": safe_date(p.get("datePosted")),
            "description": html_to_text(str(p.get("description") or "")),
        }
        full = stub.model_copy(update={k: v for k, v in update.items() if v})
        return full.model_copy(update={"remote": full.remote or remote_from_text(full.location)})
