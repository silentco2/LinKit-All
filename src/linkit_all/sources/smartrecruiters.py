"""SmartRecruiters public postings API (the list has no descriptions; details do)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://api.smartrecruiters.com/v1/companies/{board}/postings"
PAGE = 100  # the API's maximum page size
# The enrich stage only hands us the stored URL, so ids are recovered from it.
_URL = re.compile(r"smartrecruiters\.com/([\w-]+)/(\d+)", re.I)
# Company intro is boilerplate shared by every posting; it only adds noise to ranking.
_SECTIONS = ("jobDescription", "qualifications", "additionalInformation")


class SmartRecruiters(Source):
    name = "smartrecruiters"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        offset = start_page * PAGE
        while True:
            data = await http.get_json(
                API.format(board=task.board), params={"limit": PAGE, "offset": offset}
            )
            content = data.get("content") or []
            if not content:
                return
            yield [self.stub(j, task.board) for j in content]
            offset += len(content)
            if offset >= data.get("totalFound", 0):
                return

    @staticmethod
    def stub(j: dict[str, Any], board: str) -> JobStub:
        loc = j.get("location") or {}
        company = j.get("company") or {}
        ident = company.get("identifier") or board
        url = f"https://jobs.smartrecruiters.com/{ident}/{j['id']}"
        return JobStub(
            source="smartrecruiters",
            url=url,
            title=j["name"],
            company=company.get("name") or board,
            location=loc.get("fullLocation") or loc.get("city") or "",
            posted_at=from_iso(j.get("releasedDate")),
            ats="smartrecruiters",
            apply_url=url,
            remote="remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else None,
            extra={
                "board": ident,
                "id": j["id"],
                "employment": (j.get("typeOfEmployment") or {}).get("label"),
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        board, posting_id = m.groups()
        j = await http.get_json(f"{API.format(board=board)}/{posting_id}")
        sections = (j.get("jobAd") or {}).get("sections") or {}
        parts = [
            f"{s.get('title', '')}\n{html_to_text(s.get('text') or '', escaped=True)}"
            for key in _SECTIONS
            if (s := sections.get(key)) and s.get("text")
        ]
        return stub.model_copy(
            update={
                "description": "\n\n".join(parts),
                "apply_url": j.get("applyUrl") or stub.apply_url,
            }
        )
