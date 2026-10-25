"""Harri (harri.com), the hospitality ATS: a keyless gateway API for the brand lookup, a paged
job search and a JSON detail per posting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

API = "https://gateway.harri.com"
PAGE_SIZE = 100
MAX_PAGES = 100
_URL = re.compile(r"harri\.com/([^/?#]+)/job/(\d+)", re.I)


class Harri(Source):
    """The board is the brand slug of a career page: `panera-careers` for
    harri.com/panera-careers. A brand is a tree: a group lists every posting of its stores, so a
    posting's own URL names the store's slug, not the board's."""

    name = "harri"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?:www\.)?harri\.com/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slug = task.board.strip().lower()
        brand_id = await self._brand(http, slug)
        company = name_from_slug(slug)
        start = start_page * PAGE_SIZE
        for _ in range(MAX_PAGES):
            body = {
                "start": start,
                "size": PAGE_SIZE,
                "source": "web",
                "brand_level_ids": [brand_id],
                "sort": ["publish_date"],
                "sort_type": "desc",
                "flow": "CAREER_PORTAL",
            }
            url = f"{API}/core/api/v1/harri_search/search_jobs"
            data = (await http.post_json(url, body))["data"]
            batch = data.get("results") or []
            yield [s for r in batch if (s := self.stub(r, slug, company))]
            start += len(batch)
            if not batch or start >= (data.get("hits") or 0):
                return

    @staticmethod
    async def _brand(http: Http, slug: str) -> int:
        resp = await http.get(f"{API}/core/api/v1/profile/slug/{slug}")
        if resp.status_code in (400, 404):  # an unknown slug answers 400 "Slug not found"
            raise ValueError(f"harri: no brand named {slug!r}")
        resp.raise_for_status()
        profile = resp.json().get("data")
        if not isinstance(profile, dict) or not profile.get("id") or profile.get("is_archived"):
            raise ValueError(f"harri: no live brand named {slug!r}")
        if profile.get("type") != "brand":
            raise ValueError(f"harri: {slug!r} is a {profile.get('type')!r} profile, not a brand")
        return int(profile["id"])

    @staticmethod
    def stub(r: dict[str, Any], board: str, company: str) -> JobStub | None:
        raw = r.get("aliasPosition") or (r.get("position") or {}).get("name") or ""
        title = " ".join(raw.split())
        if not r.get("id") or not title:
            return None
        brand = ((r.get("brand") or {}).get("slug") or board).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        url = f"https://harri.com/{brand}/job/{r['id']}" + (f"-{slug}" if slug else "")
        places: list[str] = []
        for loc in r.get("locations") or []:
            parts: list[str] = []
            for p in (loc.get("city"), loc.get("state"), loc.get("country")):
                p = " ".join((p or "").split())
                if p and (not parts or parts[-1].lower() != p.lower()):  # the UK repeats itself
                    parts.append(p)
            if (place := ", ".join(parts)) and place not in places:
                places.append(place)
        location = "; ".join(places)
        return JobStub(
            source="harri",
            url=url,
            title=title,
            company=company,
            location=location,
            posted_at=from_iso(r.get("publishTime")),
            ats="harri",
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": board, "id": str(r["id"])},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        resp = await http.get(f"{API}/core-reader/api/v1/profile/job/{m[2]}")
        if resp.status_code in (400, 404, 410):
            return stub
        resp.raise_for_status()
        job = (resp.json().get("data") or {}).get("job") or {}
        if job.get("deleted") or job.get("status") != "PUBLISHED":  # expired postings still answer
            return stub
        codes = {(t.get("code") or "").upper() for t in job.get("Timing") or []}
        update: dict[str, Any] = {"description": html_to_text(job.get("description") or "")}
        # The arrangement has its own codes; the full/part-time schedule is not ours to guess.
        if "FULLY_REMOTE" in codes:
            update["remote"] = "remote"
        elif "HYBRID_REMOTE" in codes:
            update["remote"] = "hybrid"
        return stub.model_copy(update=update)
