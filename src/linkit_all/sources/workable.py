"""Workable public widget API: one call returns every published job with its description."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

WIDGET = "https://apply.workable.com/api/v1/widget/accounts/{board}?details=true"
DETAIL = "https://apply.workable.com/api/v2/accounts/{board}/jobs/{code}"
# The enrich stage only hands us the stored URL, so ids are recovered from it.
_URL = re.compile(r"apply\.workable\.com/([\w-]+)/j/(\w+)", re.I)


class Workable(Source):
    name = "workable"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = await http.get_json(WIDGET.format(board=task.board))
        company = data.get("name") or task.board.replace("-", " ").title()
        yield [self.stub(j, task.board, company) for j in data.get("jobs") or []]

    @staticmethod
    def stub(j: dict[str, Any], board: str, company: str) -> JobStub:
        url = f"https://apply.workable.com/{board}/j/{j['shortcode']}/"
        place = [j.get(k) for k in ("city", "state", "country")]
        return JobStub(
            source="workable",
            url=url,
            title=j["title"],
            company=company,
            location=", ".join(p for p in place if p),
            description=html_to_text(j.get("description") or ""),
            posted_at=from_iso(j.get("published_on")),
            ats="workable",
            apply_url=f"{url}apply/",
            remote="remote" if j.get("telecommuting") else None,
            extra={"board": board, "id": j["shortcode"], "employment": j.get("employment_type")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        board, code = m.groups()
        j = await http.get_json(DETAIL.format(board=board, code=code))
        parts = (html_to_text(j.get(k) or "") for k in ("description", "requirements", "benefits"))
        return stub.model_copy(update={"description": "\n\n".join(p for p in parts if p)})
