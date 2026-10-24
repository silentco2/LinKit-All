"""Ashby public job board API (descriptions and compensation included)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"
_REMOTE: dict[str, Remote] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


class Ashby(Source):
    name = "ashby"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.I),)
    parallel = 4  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = await http.get_json(
            API.format(board=task.board), params={"includeCompensation": "true"}
        )
        yield [self.stub(j, task.board) for j in data["jobs"] if j.get("isListed", True)]

    @staticmethod
    def stub(j: dict[str, Any], board: str) -> JobStub:
        locations = [j.get("location") or ""]
        locations += [s.get("location", "") for s in j.get("secondaryLocations") or []]
        remote = _REMOTE.get((j.get("workplaceType") or "").lower())
        if remote is None and j.get("isRemote"):
            remote = "remote"
        salary: dict[str, Any] = next(
            (
                c
                for c in (j.get("compensation") or {}).get("summaryComponents") or []
                if c.get("compensationType") == "Salary"
            ),
            {},
        )
        return JobStub(
            source="ashby",
            url=j["jobUrl"],
            title=j["title"],
            company=board.replace("-", " ").title(),
            location="; ".join(loc for loc in locations if loc),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or ""),
            posted_at=from_iso(j.get("publishedAt")),
            ats="ashby",
            apply_url=j.get("applyUrl"),
            remote=remote,
            salary_min=salary.get("minValue"),
            salary_max=salary.get("maxValue"),
            salary_currency=salary.get("currencyCode"),
            salary_interval=(salary.get("interval") or "").replace("1 ", "").lower() or None,
            extra={"board": board, "id": j["id"], "employment": j.get("employmentType")},
        )
