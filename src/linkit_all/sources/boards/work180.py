"""WORK180 (work180.com), a job board listing only employers endorsed as supporting women at work.
One task per region sitemap; the posting page gives the JobPosting block and, in its Next.js
flight data, the employer's own apply link. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f16 import ld_stub, page_text
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.boards._f32 import ats_of, posting_pages, sitemap_text, sitemap_urls
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

BASE = "https://work180.com"
LOCALES = {"au": "en-au", "uk": "en-gb", "us": "en-us"}
MAX_NEW = 120  # pages per region per run: the site asks crawlers for a 5 s Crawl-delay
_JOB = re.compile(r"^https://work180\.com/(en-[a-z]{2})/for-women/employer/([^/]+)/job/(\d+)", re.I)
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _flight_job(html: str, job_id: str) -> dict[str, Any]:
    """The `job` record the page's flight data carries for this posting ({} if absent)."""
    flight = "".join(json.loads(m[1]) for m in _PUSH.finditer(html))
    marker = f'"job":{{"id":"{job_id}"'
    at = flight.find(marker)
    if at < 0:
        return {}
    try:
        rec, _ = json.JSONDecoder().raw_decode(flight, at + len('"job":'))
    except ValueError:
        return {}
    return rec if isinstance(rec, dict) else {}


class Work180(Source):
    name = "work180"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        s = cfg.search
        return [
            Task(self.name, f"work180:{region}", board=region,
                 limit=min(s.max_results_per_query * max(1, len(s.queries)), MAX_NEW),
                 posted_within_days=s.posted_within_days)
            for region in LOCALES
        ]  # fmt: skip

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        locale = LOCALES.get(task.board)
        if locale is None:
            raise ValueError(f"work180: unknown region {task.board!r} (want au, uk or us)")
        xml = await sitemap_text(http, f"{BASE}/{locale}/jobs-sitemap.xml")
        urls = sitemap_urls(xml, lambda u: bool((m := _JOB.match(u)) and m[1] == locale))
        urls.sort(key=lambda u: int(_JOB.match(u)[3]), reverse=True)  # type: ignore[index]

        async def build(url: str) -> JobStub | None:
            text = await page_text(http, url)
            postings = job_postings(text) if text else []
            m = _JOB.match(url)
            if not postings or not m or not text:
                return None
            ident = postings[0].get("identifier") or {}
            if str(ident.get("value", "")).strip() != m[3]:
                return None
            rec = _flight_job(text, m[3])
            if rec.get("expired"):  # the page says the posting has closed
                return None
            company = (postings[0].get("hiringOrganization") or {}).get("name") or (
                (rec.get("employer") or {}).get("name") or ""
            )
            stub = ld_stub(
                postings[0], source=self.name, url=url, company=company,
                extra={"id": m[3], "employer": m[2]},
            )  # fmt: skip
            if stub is None or not stub.company or not stub.description:
                return None
            link = (rec.get("applicationLink") or "").strip()
            external = rec.get("applicationType") == "EXTERNAL" and link.startswith("http")
            places = postings[0].get("jobLocation") or []
            names = [
                (p.get("address") or {}).get("name")
                for p in (places if isinstance(places, list) else [places])
                if isinstance(p, dict)
            ]
            return stub.model_copy(
                update={
                    "location": "; ".join(dict.fromkeys(n for n in names if n)) or stub.location,
                    "apply_url": link if external else url,
                    "ats": ats_of(link if external else None, self.name),
                }
            )

        async for page in posting_pages(urls, start_page, task.limit, build):
            yield page
