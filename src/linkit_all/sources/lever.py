"""Lever public postings API (global and EU instances)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_epoch_ms
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

HOSTS = ("https://api.lever.co", "https://api.eu.lever.co")
_REMOTE: dict[str, Remote] = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}


class Lever(Source):
    name = "lever"
    parallel = 4  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        for host in HOSTS:  # boards live on exactly one instance; the other answers 404
            resp = await http.get(f"{host}/v0/postings/{task.board}", params={"mode": "json"})
            if resp.status_code != 404:
                resp.raise_for_status()
                yield [self.stub(j, task.board) for j in resp.json()]
                return
        resp.raise_for_status()

    @staticmethod
    def stub(j: dict[str, Any], board: str) -> JobStub:
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description") or "")]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content') or '')}")
        parts.append(j.get("additionalPlain") or "")
        salary = j.get("salaryRange") or {}
        return JobStub(
            source="lever",
            url=j["hostedUrl"],
            title=j["text"],
            company=board.replace("-", " ").title(),
            location=cats.get("location") or "",
            description="\n\n".join(p.strip() for p in parts if p and p.strip()),
            posted_at=from_epoch_ms(j.get("createdAt")),
            ats="lever",
            apply_url=j.get("applyUrl"),
            remote=_REMOTE.get((j.get("workplaceType") or "").lower()),
            salary_min=salary.get("min"),
            salary_max=salary.get("max"),
            salary_currency=salary.get("currency"),
            salary_interval=salary.get("interval"),
            extra={"board": board, "id": j["id"], "commitment": cats.get("commitment")},
        )
