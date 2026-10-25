"""Solides vacancies (Brazil, {board}.vagas.solides.com.br) from the public jobs gateway, which
returns the description inline. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug, when

_API = "https://apigw.solides.com.br/jobs/v3/home/vacancy"
_OPEN = "em_andamento"  # any other present currentState ("encerrada") is a closed vacancy
_MODES: dict[str, Remote] = {"remoto": "remote", "hibrido": "hybrid", "presencial": "onsite"}


class Solides(Source):
    name = "solides"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.vagas\.solides\.com\.br", re.I),)
    cdx_hosts = ("*.vagas.solides.com.br",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slug = quote(task.board.lower(), safe="")
        for page in range(start_page + 1, 1001):  # the server caps `take` at 25
            body = await http.get_json(f"{_API}?slug={slug}&take=25&page={page}")
            data = (body.get("data") if isinstance(body, dict) else None) or {}
            rows = data.get("data") or []
            yield [
                self._stub(r, task.board)
                for r in rows
                if r.get("id") and r.get("currentState") in (None, "", _OPEN)
            ]
            if not rows or page >= (data.get("totalPages") or 0):
                return

    def _stub(self, row: dict[str, Any], board: str) -> JobStub:
        url = f"https://{board.lower()}.vagas.solides.com.br/vaga/{row['id']}"
        city = (row.get("city") or {}).get("name") or ""
        state = (row.get("state") or {}).get("code") or ""
        mode = _MODES.get(str(row.get("jobType") or "").strip().lower())
        return JobStub(
            source=self.name,
            url=url,
            title=" ".join(str(row.get("title") or "").split()),
            company=name_from_slug(board),
            location=", ".join(p.strip() for p in (city, state) if p.strip()),
            description=strip_html(row.get("description") or ""),
            posted_at=when(row.get("createdAt")),
            ats=self.name,
            apply_url=url,
            remote="remote" if row.get("homeOffice") else mode,
            extra={"board": board, "id": str(row["id"])},
        )
