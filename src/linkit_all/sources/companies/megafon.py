"""MegaFon careers (job.megafon.ru): the city list, then each city's vacancy list, then a detail
request per vacancy for the body. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_epoch_ms
from linkit_all.sources.companies._f43 import (
    careers_task,
    json_or_none,
    rub_month,
    sections,
)
from linkit_all.sources.http import Http

CITIES = "https://job.megafon.ru/api/v1/cities/available"
LIST = "https://job.megafon.ru/api/v1/vacancies?cities={city}&page={page}"
DETAIL = "https://job.megafon.ru/api/v1/vacancies/{slug}?cityId={city}"
JOB = "https://job.megafon.ru/vacancy/"
MAX_PAGES = 100
REMOTE_CITY = "udalennyj-format"
ALL_CITIES = "vse-goroda"
# The unfiltered feed is ordered by publication time alone and drops postings between pages
# (hundreds share one timestamp), so the list is walked city by city (one page per city per
# `start_page`), which is slow (about 700 cities) but complete.


class Megafon(Source):
    name = "megafon"
    kind = "company"

    def __init__(self) -> None:
        self._city_ids: dict[str, int] = {}

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def _cities(self, http: Http) -> list[dict[str, Any]]:
        cities: list[dict[str, Any]] = (await http.get_json(CITIES)).get("cities") or []
        self._city_ids = {c["slug"]: c["id"] for c in cities if c.get("slug") and c.get("id")}
        return cities

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[int] = set()  # a posting is listed under every city it covers; keep the first
        for city in (await self._cities(http))[start_page:]:
            stubs = []
            for v in await self._city_vacancies(http, city["id"]):
                if v.get("id") and v["id"] not in seen and (stub := self.stub(v)):
                    seen.add(v["id"])
                    stubs.append(stub)
            yield stubs

    @staticmethod
    async def _city_vacancies(http: Http, city_id: int) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            data = await http.get_json(LIST.format(city=city_id, page=page))
            found += data.get("vacancies") or []
            if not data.get("vacancies") or page >= (data.get("pages") or 1):
                break
        return found

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(v.get("title") or "").split())
        if not title or not v.get("slug"):
            return None
        city = v.get("city") or {}
        slug = city.get("slug") or ""
        sector = (v.get("sector") or {}).get("slug") or ""
        tag = (v.get("tag") or {}).get("code")
        mode: Remote | None = None
        if tag == "hybrid_shift":
            mode = "hybrid"
        elif tag == "remote" or slug == REMOTE_CITY:
            mode = "remote"
        url = JOB + "/".join(p for p in (slug, sector, v["slug"]) if p)
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            # MegaFon publishes for several entities; the posting's own one is the employer.
            company=(v.get("organisation") or {}).get("title") or "MegaFon",
            location="Россия" if slug in (REMOTE_CITY, ALL_CITIES) else city.get("title") or "",
            posted_at=from_epoch_ms((v.get("publishedAt") or 0) * 1000),
            ats=self.name,
            remote=mode,
            extra={"megafon_id": v["id"], "city_id": city.get("id"), "sector": sector},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        parts = urlsplit(stub.url).path.strip("/").split("/")  # vacancy/<city>[/<sector>]/<slug>
        if not self._city_ids:
            await self._cities(http)
        city_id = self._city_ids.get(parts[1]) if len(parts) >= 3 else None
        d = (
            await json_or_none(http, DETAIL.format(slug=parts[-1], city=city_id))
            if city_id
            else None
        )
        if not d:
            return stub
        return stub.model_copy(
            update={
                "description": sections(
                    ("Обязанности", d.get("description")),
                    ("Требования", d.get("requirements")),
                    ("Условия", d.get("conditions")),
                ),
                **rub_month(d.get("minSalary"), d.get("maxSalary")),
            }
        )
