"""jobappnetwork.com career sites (vendor: talentReef): one numeric client id is one employer's
whole account. A keyless POST to the platform's search proxy returns each posting with its full
body, so no detail request is needed. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

SEARCH = "https://prod-kong.internal.talentreef.com/apply/proxy-es/search-en-us/posting/_search"
APPLY = "https://apply.jobappnetwork.com/clients/{client}/posting/{id}/"
PAGE_SIZE = 100


def query(client: int, offset: int) -> dict[str, Any]:
    """One page of the client's listing. `externalOnly` is part of the query, so a posting meant
    only for internal-transfer applicants never leaves the server."""
    return {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"clientId": client}},
                    {"term": {"internalOrExternal": "externalOnly"}},
                ]
            }
        },
        "from": offset,
        "size": PAGE_SIZE,
    }


class JobAppNetwork(Source):
    """The board is the numeric client id from apply.jobappnetwork.com/clients/<id>/..."""

    name = "jobappnetwork"
    kind = "ats"
    url_patterns = (re.compile(r"jobappnetwork\.com/clients/(\d+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if not task.board.isdigit() or int(task.board) <= 0:
            raise ValueError(f"jobappnetwork: board {task.board!r} must be a numeric client id")
        client = int(task.board)

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.post_json(SEARCH, query(client, offset))
            hits = data.get("hits") or {}
            total = hits.get("total")  # a number, or {"value": n} on newer Elasticsearch
            total = total.get("value") if isinstance(total, dict) else total
            return [h.get("_source") or {} for h in hits.get("hits") or []], total

        async for rows in paged(fetch, PAGE_SIZE, start_page):
            yield [self.stub(r, client) for r in rows if r.get("jobId")]

    def stub(self, p: dict[str, Any], client: int) -> JobStub:
        addr = p.get("address") or {}
        where = ", ".join(
            x for x in (addr.get("city"), addr.get("stateOrProvince"), addr.get("country")) if x
        )
        url = APPLY.format(client=client, id=p["jobId"])
        return JobStub(
            source=self.name,
            url=url,
            title=(p.get("title") or "").strip(),
            company=f"Client {client}",  # the proxy does not name the employer
            location=where,
            description=html_to_text(p.get("description") or ""),
            posted_at=from_iso(p.get("createdDate")),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(where),
            extra={"board": str(client), "id": str(p["jobId"])},
        )
