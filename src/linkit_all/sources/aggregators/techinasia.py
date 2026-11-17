"""Tech in Asia (www.techinasia.com/jobs), startup jobs in Southeast Asia, read through the
public Algolia search index its own jobs page calls. The app id and client search key change
with the site's build, so they are read from the page's current app script on every run; the
key only answers with a techinasia.com Referer, which the page sends too. The whole index is
read (not the page's default Indonesia filter). An employer link shared by several postings
(one intake form for many roles) or behind a URL shortener is not used as the posting address.
Logic adapted from career-ops (MIT)."""

import json
import re
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date
from linkit_all.sources.tasks import feed_task

SEARCH_PAGE = "https://www.techinasia.com/jobs/search"
JOB = "https://www.techinasia.com/jobs/{}"
INDEX = "job_postings"
HITS = 1000
MAX_PAGES = 50
_ASSET = re.compile(r"//static\.techinasia\.com(/assets/v5/app\.[0-9a-f]{8}\.js)")
_KEYS = re.compile(r'apiKey:\s*"([A-Za-z0-9]{16,64})"\s*,\s*appId:\s*"([A-Za-z0-9]{6,16})"')
_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "rebrand.ly", "s.id", "cutt.ly"}


def _company(raw: Any) -> str:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return ""
    return clean(raw.get("name")) if isinstance(raw, dict) else ""


class TechInAsia(Source):
    name = "techinasia"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # every hit is gathered first (shared links need the whole board)
            return
        m = _ASSET.search((await get_page(http, SEARCH_PAGE)).text)
        if not m:
            raise ValueError("techinasia: no app script on the jobs page")
        keys = _KEYS.search((await get_page(http, f"https://static.techinasia.com{m[1]}")).text)
        if not keys:
            raise ValueError("techinasia: no search key in the app script")
        api_key, app_id = keys[1], keys[2]
        endpoint = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes/*/queries"
        params = {"x-algolia-application-id": app_id, "x-algolia-api-key": api_key}
        headers = {"Referer": "https://www.techinasia.com/", "Accept": "application/json"}
        hits: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            q = f"query=&hitsPerPage={HITS}&page={page}"
            body = {"requests": [{"indexName": INDEX, "params": q}]}
            # The page posts JSON text under a form content type; the same bytes are sent here.
            resp = await http.request(
                "POST",
                endpoint,
                params=params,
                content=json.dumps(body),
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            results = resp.json().get("results") or [{}]
            got = [h for h in results[0].get("hits") or [] if isinstance(h, dict)]
            hits += got
            if not got or page + 1 >= int(results[0].get("nbPages") or 1):
                break
        shared = Counter(self.external(h) for h in hits)
        stubs = [s for h in hits if (s := self.stub(h, shared))][: task.limit]
        if stubs:
            yield stubs

    @staticmethod
    def external(h: dict[str, Any]) -> str:
        link = str(h.get("external_link") or "").strip()
        host = (urlsplit(link).hostname or "").lower()
        return link if link.startswith("https://") and host not in _SHORTENERS else ""

    def stub(self, h: dict[str, Any], shared: Counter[str]) -> JobStub | None:
        title, company = clean(h.get("title")), _company(h.get("company"))
        jid = str(h.get("id") or h.get("objectID") or "").strip()
        own = JOB.format(quote(jid, safe="")) if jid else ""
        link = self.external(h)
        url = link if link and shared[link] == 1 else own
        if not (title and company and url):
            return None
        city: dict[str, Any] = h["city"] if isinstance(h.get("city"), dict) else {}
        parts = [clean(city.get(k)) for k in ("name", "country_name")]
        places = list(dict.fromkeys(p for p in parts if p))
        if h.get("is_remote"):
            places.append("Remote")
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=", ".join(places),
            description=strip_html(h.get("description") or ""),
            posted_at=safe_date(h.get("published_at")),
            ats=self.name,
            apply_url=url,
            remote="remote" if h.get("is_remote") else None,
            extra={"id": jid or url, "page": own},
        )
