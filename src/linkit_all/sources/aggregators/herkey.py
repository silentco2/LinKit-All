"""HerKey (herkey.com, formerly JobsForHer), an India-focused job platform for women. The site's
backend lists jobs without a body (its anonymous visitor session is minted from a public endpoint,
as the site's own pages do); `fetch_details` reads each job's own resource. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

API = "https://api-prod.herkey.com/api/v1/herkey/"
JOB_URL = "https://www.herkey.com/jobs/{}/{}"
PAGE = 500  # served as asked
MAX_PAGES = 40
CHUNK = 100  # stubs per yielded page
IST = timezone(timedelta(hours=5, minutes=30))  # the API's zone-less stamps are India time
_REDIRECTORS = {"jsv3.recruitics.com": "rx_url"}  # tracking redirects wrapping the employer link
_MODES: dict[str, Remote] = {"work_from_home": "remote", "work_from_office": "onsite",
                             "hybrid": "hybrid"}  # fmt: skip


def _time(value: str | None) -> datetime | None:
    try:
        stamp = datetime.strptime((value or "").strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return stamp.replace(tzinfo=IST).astimezone(UTC).replace(tzinfo=None)


def _link(raw: str | None) -> str:
    """The employer's own posting link, unwrapped from a tracking redirect; "" when unusable."""
    url = (raw or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    if param := _REDIRECTORS.get(parts.hostname or ""):
        inner = (parse_qs(parts.query).get(param) or [""])[0]
        return inner if inner.startswith(("http://", "https://")) else ""
    return url


def _mode(values: list[str]) -> Remote | None:
    """The single arrangement a row ticks; several different ones state none."""
    modes = {_MODES.get(v.strip()) for v in values if v.strip()}
    return modes.pop() if len(modes) == 1 else None


class HerKey(Source):
    name = "herkey"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        sess = await http.get_json(API + "generate-session")
        token = (sess.get("body") or {}).get("session_id")
        if not token:
            raise ValueError("herkey: no session id")
        headers = {"Authorization": f"Token {token}"}
        rows: dict[int, dict[str, Any]] = {}
        for page in range(1, MAX_PAGES + 1):
            data = await http.get_json(
                API + "jobs/es_candidate_jobs",
                params={"page_no": page, "page_size": PAGE},
                headers=headers,
            )
            rows.update({r["id"]: r for r in data.get("body") or [] if r.get("id")})
            if not (data.get("pagination") or {}).get("has_next") or not data.get("body"):
                break
        cutoff = utcnow() - timedelta(days=task.posted_within_days)
        stubs = [
            s for r in rows.values() if (s := self.stub(r)) and (s.posted_at or cutoff) >= cutoff
        ]
        stubs.sort(key=lambda s: s.posted_at or cutoff, reverse=True)  # the cap keeps the newest
        stubs = stubs[: task.limit]
        for i in range(start_page * CHUNK, len(stubs), CHUNK):
            yield stubs[i : i + CHUNK]

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        title, company = " ".join((r.get("title") or "").split()), (r.get("company_name") or "")
        if not (r.get("id") and title and company.strip()):
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "job"
        url = JOB_URL.format(slug, r["id"])  # the id is the last segment, for fetch_details
        place = (r.get("location_name") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company.strip(),
            location="" if place.lower() == "any" else place,  # "Any" is not a place
            posted_at=_time(r.get("created_on")),
            apply_url=_link(r.get("redirect_url")) or url,
            remote=_mode(r.get("work_mode") or []),
            ats=self.name,
            extra={"id": r["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        job_id = stub.url.rstrip("/").rsplit("/", 1)[-1]
        resp = await http.get(f"{API}jobs/jobs/{job_id}")
        if resp.status_code in (400, 404, 410):  # the index keeps listing expired jobs
            return stub
        resp.raise_for_status()
        body = next((b for b in resp.json().get("body") or [] if str(b.get("id")) == job_id), None)
        if not body or body.get("status") != "active":
            return stub
        parts = [
            strip_html(p)
            for k in ("description", "responsibilities", "requirements")
            if (p := body.get(k)) and p.strip().strip("\"'").lower() not in ("tbd", "none")
        ]  # imported postings sometimes hold a "TBD" placeholder
        update: dict[str, Any] = {"description": "\n\n".join(p for p in parts if p)}
        if posted := _time(body.get("published_on")):
            update["posted_at"] = posted
        return stub.model_copy(update=update)
