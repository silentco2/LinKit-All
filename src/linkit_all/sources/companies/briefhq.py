"""Brief's own careers page (briefhq.ai/careers): a hand-rolled static page that inlines every
vacancy as a schema.org JobPosting block. A single-company plugin, not an ATS. Logic adapted
from freehire (MIT)."""

from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub

PAGE = "https://briefhq.ai/careers/"


class BriefHQ(Source):
    name = "briefhq"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "briefhq:careers", board=PAGE)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        if not await http.allowed(task.board):
            raise Unsupported(f"robots.txt does not allow fetching {task.board}")
        resp = await http.get(task.board)
        resp.raise_for_status()
        stubs = []
        for p in job_postings(resp.text):
            slug = (
                (p.get("identifier") or {}).get("value")
                if isinstance(p.get("identifier"), dict)
                else None
            )
            url = p.get("url") or (f"{task.board}#{slug}" if slug else task.board)
            stub = to_stub(p, self.name, url, None)
            if stub.title and stub.title != "None":
                stubs.append(stub.model_copy(update={"extra": {**stub.extra, "id": slug or url}}))
        yield stubs
