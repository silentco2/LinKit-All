"""DomClick careers (career.domclick.ru): a JSON vacancy list with the work format, and the body
in a per-slug detail call. Single-company plugin. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ats_of, first, remote_ru

API = "https://career.domclick.ru/api/v1/vacancy/"
JOB = "https://career.domclick.ru/vacancy/"


def work_mode(formats: list[str], place: str) -> Remote | None:
    """The API's work_format enum (REMOTE / HYBRID / ON_SITE); the place text if it has none."""
    if "REMOTE" in formats:
        return "remote"
    if "HYBRID" in formats:
        return "hybrid"
    return "onsite" if formats == ["ON_SITE"] else remote_ru(place)


class Domclick(Source):
    name = "domclick"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "domclick:vacancies")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        data = await http.get_json(API)
        stubs = [s for v in data.get("result") or [] if (s := self.stub(v))]
        if start_page == 0 and stubs:
            yield stubs

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(v.get("title") or "").split())
        if not v.get("slug") or not title:
            return None
        url = JOB + v["slug"]
        place = str((v.get("area") or {}).get("name") or "").strip()
        formats = (v.get("vacancycontent") or {}).get("work_format") or []
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="DomClick",
            location=place,
            ats=ats_of(url, self.name),
            apply_url=url,
            remote=work_mode(formats, place),
            extra={"id": v["slug"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if stub.description:
            return stub
        slug = stub.url.rstrip("/").rsplit("/", 1)[-1]
        data = await http.get_json(f"{API}detail/{slug}/")
        content = (data.get("result") or {}).get("vacancycontent") or {}
        body = first(content, "branded_description", "description")
        return stub.model_copy(update={"description": strip_html(body)})
