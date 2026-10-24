"""Vention's own careers site (join.ventionteams.com, the iTechArt rebrand): the Wagtail CMS behind
the SPA serves every vacancy, body included, from a keyless JSON API. A single-company plugin, not
an ATS. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

HOST = "join.ventionteams.com"
PAGE = 20
API = "https://{host}/api/v2/pages/?type=join_vacancy.VacancyPage&fields=*&limit={limit}&offset={offset}"


def work_mode(work_format: str | None) -> Remote | None:
    """Vention's work_format: "remote", or something ending in "hybrid" / "onsite" / "office"."""
    f = (work_format or "").lower()
    if f == "remote":
        return "remote"
    if "hybrid" in f:
        return "hybrid"
    return "onsite" if "onsite" in f or "office" in f else None


class Vention(Source):
    name = "vention"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "vention:careers", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(API.format(host=task.board, limit=PAGE, offset=offset))
            return data.get("items") or [], (data.get("meta") or {}).get("total_count")

        async for items in paged(fetch, PAGE, start_page):
            yield [self.stub(v, task.board) for v in items if v.get("id") and v.get("title")]

    @staticmethod
    def stub(v: dict[str, Any], host: str) -> JobStub:
        meta = v.get("meta") or {}
        city = v.get("city") or {}
        place = (city.get("name"), (city.get("country") or {}).get("name"))
        location = ", ".join(p for p in place if p)
        url = meta.get("html_url") or f"https://{host}/job-openings/{meta.get('slug')}"
        blocks = ("responsibilities", "required_skills", "about", "benefits")
        return JobStub(
            source="vention",
            url=url,
            title=" ".join(v["title"].split()),
            company="Vention",
            location=location,
            description=html_to_text("".join(v.get(b) or "" for b in blocks)),
            posted_at=from_iso(meta.get("first_published_at")),
            apply_url=url,
            remote=work_mode(v.get("work_format")) or remote_from_text(location),
            extra={"id": str(v["id"]), "work_format": v.get("work_format")},
        )
