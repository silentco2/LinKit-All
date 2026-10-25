"""Welcome to the Jungle (welcometothejungle.com), a European job board read through the public
Algolia index its own search page queries. Logic adapted from freehire (MIT)."""

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import json_or_none
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ats_of, distinct, sections
from linkit_all.sources.tasks import company_query_tasks

ENV = "https://www.welcometothejungle.com/api/env"
REFERER = {"Referer": "https://www.welcometothejungle.com/"}  # the Algolia key is locked to it
INDEX = "wttj_jobs_production_en"
QUERY = "https://{}-dsn.algolia.net/1/indexes/" + INDEX + "/query"
PAGE = "https://www.welcometothejungle.com/en/companies/{}/jobs/{}"
DETAIL = "https://api.welcometothejungle.com/api/v1/organizations/{}/jobs/{}"
CAP = 1000  # Algolia serves at most this many hits per query, so a larger window is halved
ATTRIBUTES = [
    "objectID", "name", "slug", "organization.name", "organization.slug", "offices", "remote",
    "salary_minimum", "salary_maximum", "salary_currency", "salary_period", "published_at",
]  # fmt: skip
_APP_ID = re.compile(r"^[A-Za-z0-9]{6,16}$")  # becomes a hostname, so its shape is checked
_SLUG = re.compile(r"^[A-Za-z0-9_-]+$")  # spliced into paths
_POSTING = re.compile(r"/companies/([\w-]+)/jobs/([\w-]+)")
_REMOTE = {"fulltime": "remote", "partial": "hybrid", "no": "onsite"}  # "punctual": left unsaid
_PERIOD = {"yearly": "year", "monthly": "month", "daily": "day", "hourly": "hour"}


class WelcomeToTheJungle(Source):
    name = "wttj"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        # Algolia filters by the text query; places are left to our own matching filters.
        return company_query_tasks(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        url, headers = await self._credentials(http)

        async def ask(lo: int, hi: int, per_page: int) -> dict[str, Any]:
            params = {
                "query": task.query,
                "filters": f"published_at_timestamp >= {lo} AND published_at_timestamp < {hi}",
                "hitsPerPage": per_page,
                "distinct": "false",  # the index collapses by an attribute: 7,577 hits became 1,531
                "analytics": "false",
                "attributesToRetrieve": json.dumps(ATTRIBUTES),
                "attributesToHighlight": "[]",
            }
            return dict(await http.post_json(url, {"params": urlencode(params)}, headers=headers))

        async def windows(lo: int, hi: int, count: int) -> AsyncIterator[tuple[int, int, int]]:
            """Time windows holding at most CAP postings each, newest first."""
            if count <= CAP or hi - lo <= 1:  # ponytail: >CAP in one second is read truncated
                if count:
                    yield lo, hi, count
                return
            mid = (lo + hi) // 2
            for a, b in ((mid, hi), (lo, mid)):
                async for w in windows(a, b, (await ask(a, b, 0)).get("nbHits", 0)):
                    yield w

        # ponytail: windows hang off `now`, so a resume days later may shift page boundaries
        now = int(time.time())
        lo, hi = now - task.posted_within_days * 86400, now + 3600
        left, page = task.limit, 0
        async for a, b, count in windows(lo, hi, (await ask(lo, hi, 0)).get("nbHits", 0)):
            if left <= 0:
                return
            if page >= start_page:  # a resumed run skips the pages it already stored
                hits = (await ask(a, b, min(count, left))).get("hits") or []
                stubs = [s for h in hits if (s := self.stub(h))]
                yield stubs  # empty pages too: the checkpoint counts yielded pages
                left -= len(hits)
            else:
                left -= count
            page += 1

    async def _credentials(self, http: Http) -> tuple[str, dict[str, str]]:
        """The Algolia query URL and headers; the site publishes its search key at /api/env,
        and it is the site's to rotate, so it is read at the start of every task."""
        resp = await http.get(ENV, headers=REFERER)
        resp.raise_for_status()
        text = resp.text  # a "window.env = {...};" script
        env = json.loads(text[text.index("{") : text.rindex("}") + 1])
        app_id = str(env.get("PUBLIC_ALGOLIA_APPLICATION_ID") or "").strip()
        key = str(env.get("PUBLIC_ALGOLIA_API_KEY_CLIENT") or "").strip()
        if not (_APP_ID.match(app_id) and key):
            raise ValueError("wttj: /api/env carries no usable Algolia credentials")
        headers = {"X-Algolia-Application-Id": app_id, "X-Algolia-API-Key": key, **REFERER}
        return QUERY.format(app_id), headers

    def stub(self, h: dict[str, Any]) -> JobStub | None:
        org = h.get("organization") or {}
        slug, org_slug = h.get("slug") or "", org.get("slug") or ""
        title, company = (h.get("name") or "").strip(), (org.get("name") or "").strip()
        if not (h.get("objectID") and title and company):
            return None
        if not (_SLUG.match(slug) and _SLUG.match(org_slug)):
            return None
        offices = h.get("offices") or []
        stub = JobStub(
            source=self.name,
            url=PAGE.format(org_slug, slug),
            title=title,
            company=company,
            location=distinct(
                [", ".join(filter(None, [o.get("city"), o.get("country")])) for o in offices]
            ),
            posted_at=from_iso(h.get("published_at")),
            remote=_REMOTE.get(h.get("remote") or "") or remote_from_text(title),
            ats=self.name,
            extra={"id": h["objectID"], "org": org_slug, "slug": slug},
        )
        period, currency = _PERIOD.get(h.get("salary_period") or ""), h.get("salary_currency")
        low, high = h.get("salary_minimum") or None, h.get("salary_maximum") or None
        if period and currency and (low or high):  # an unknown period drops the whole salary
            stub.salary_min, stub.salary_max = low, high
            stub.salary_currency, stub.salary_interval = str(currency).upper(), period
        return stub

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not (m := _POSTING.search(stub.url)):
            return stub
        data = await json_or_none(http, DETAIL.format(*m.groups()))
        job = (data or {}).get("job") or {}
        ref = stub.extra.get("id")
        # The API is addressed by slugs, the index by uuid: a reused slug must not file another
        # posting's body under this one.
        if job.get("status") != "published" or (ref and job.get("wttj_reference") != ref):
            return stub
        apply_url = (job.get("apply_url") or "").strip()
        if apply_url.startswith(("http://", "https://")):
            stub.apply_url, stub.ats = apply_url, ats_of(apply_url, self.name)
        stub.description = sections(
            ("", job.get("description")),
            ("Profile", job.get("profile")),
            ("Recruitment process", job.get("recruitment_process")),
        )
        return stub
