"""Greenhouse public job board API (one call returns every job with its description)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class Greenhouse(Source):
    name = "greenhouse"
    kind = "ats"
    url_patterns = (  # the embed form must come before the plain board form
        re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([\w-]+)", re.I),
        re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([\w-]+)", re.I),
        re.compile(r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)", re.I),
    )
    parallel = 4  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = await http.get_json(API.format(board=task.board), params={"content": "true"})
        yield [self.stub(j, task.board) for j in data["jobs"]]

    @staticmethod
    def stub(j: dict[str, Any], board: str) -> JobStub:
        location = (j.get("location") or {}).get("name", "")
        return JobStub(
            source="greenhouse",
            url=j["absolute_url"],
            title=j["title"],
            company=j.get("company_name") or board.replace("-", " ").title(),
            location=location,
            description=html_to_text(j.get("content") or "", escaped=True),
            posted_at=from_iso(j.get("first_published") or j.get("updated_at")),
            ats="greenhouse",
            apply_url=j["absolute_url"],
            remote=remote_from_text(location),
            extra={"board": board, "id": j["id"]},
        )
