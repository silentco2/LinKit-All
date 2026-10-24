"""BambooHR public careers API ({board}.bamboohr.com/careers/list). Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://{board}.bamboohr.com/careers/list"
DETAIL = "https://{board}.bamboohr.com/careers/{id}/detail"
JOB_URL = "https://{board}.bamboohr.com/careers/{id}"
_URL = re.compile(r"//([\w-]+)\.bamboohr\.com/careers/(\d+)", re.I)
# locationType is the only structured work-mode signal in the list; isRemote is mostly null.
_MODES: dict[str, Remote] = {"0": "onsite", "1": "remote", "2": "hybrid"}


def place(loc: dict[str, Any] | None) -> str:
    loc = loc or {}
    parts = (loc.get("city"), loc.get("state") or loc.get("province"), loc.get("addressCountry"))
    return ", ".join(dict.fromkeys(str(p).strip() for p in parts if p and str(p).strip()))


class BambooHR(Source):
    name = "bamboohr"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.bamboohr\.com", re.I),)
    parallel = 4  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        board = task.board
        resp = await http.get(LIST.format(board=board))
        # BambooHR says "not serving this board" with a redirect off /careers (no such tenant,
        # board switched off, account lapsed or suspended), so the landing page tells it apart.
        if f"{board}.bamboohr.com/careers".lower() not in str(resp.url).lower():
            raise Unsupported(f"bamboohr board {board} is not served (redirected to {resp.url})")
        resp.raise_for_status()
        company = board.replace("-", " ").title()
        yield [self.stub(j, board, company) for j in resp.json().get("result") or [] if j.get("id")]

    @staticmethod
    def stub(j: dict[str, Any], board: str, company: str) -> JobStub:
        url = JOB_URL.format(board=board, id=j["id"])
        # `location` is the display address, `atsLocation` the structured one; either may be absent.
        where = place(j.get("location")) or place(j.get("atsLocation"))
        remote = _MODES.get(str(j.get("locationType"))) or ("remote" if j.get("isRemote") else None)
        return JobStub(
            source="bamboohr",
            url=url,
            title=(j.get("jobOpeningName") or "").strip(),
            company=company,
            location=where,
            ats="bamboohr",
            apply_url=url,
            remote=remote,
            extra={
                "board": board,
                "id": str(j["id"]),
                "employment": j.get("employmentStatusLabel"),
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        board, job = m.groups()
        data = await http.get_json(DETAIL.format(board=board, id=job))
        opening = (data.get("result") or {}).get("jobOpening") or {}
        if not opening.get("jobOpeningShareUrl"):  # a 200 that is not an answer
            return stub
        return stub.model_copy(
            update={
                "description": html_to_text(opening.get("description") or ""),
                "location": place(opening.get("location")) or stub.location,
                "posted_at": from_iso(opening.get("datePosted")) or stub.posted_at,
            }
        )
