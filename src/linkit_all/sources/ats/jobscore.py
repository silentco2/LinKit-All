"""JobScore (careers.jobscore.com): a keyless per-company feed.json carries every posting in full.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

# JobScore asks integrations to poll a feed at most once per hour; one call per run is well inside.
FEED = "https://careers.jobscore.com/jobs/{board}/feed.json?sort=date&limit=1000"


def _remote(text: str | None) -> Remote | None:
    """The free-text flag: "No | Must be able to work onsite all of the time", "Yes | Can work
    remotely some of the time" (some = hybrid)."""
    t = (text or "").strip().lower()
    if t.startswith("yes"):
        return "hybrid" if "some" in t else "remote"
    return "onsite" if t.startswith("no") else None


def _location(job: dict[str, Any]) -> str:
    city_state = ", ".join(
        p for p in (str(job.get(k) or "").strip() for k in ("city", "state")) if p
    )
    return city_state or str(job.get("country") or job.get("location") or "").strip()


class JobScore(Source):
    """The board is the company shortcode of `careers.jobscore.com/careers/<board>`."""

    name = "jobscore"
    kind = "ats"
    url_patterns = (re.compile(r"careers\.jobscore\.com/(?:careers|jobs)/([\w-]+)", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds the whole board
            return
        feed = await http.get_json(FEED.format(board=task.board))
        company = (feed.get("company_name") or "").strip() or name_from_slug(task.board)
        stubs = [s for j in feed.get("jobs") or [] if (s := self.stub(j, task.board, company))]
        yield stubs

    @staticmethod
    def stub(j: dict[str, Any], board: str, company: str) -> JobStub | None:
        job_id = str(j.get("id") or "").strip()
        title = " ".join(str(j.get("title") or "").split())
        if not job_id or not title:
            return None
        url = (j.get("detail_url") or "").split("?")[0] or (
            f"https://careers.jobscore.com/careers/{board}/jobs/{job_id}"
        )
        opened = j.get("opened_date")
        return JobStub(
            source="jobscore",
            url=url,
            title=title,
            company=company,
            location=_location(j),
            description=strip_html(j.get("description") or ""),
            posted_at=from_iso(opened) if opened else None,
            ats="jobscore",
            apply_url=url,
            remote=_remote(j.get("remote")),
            extra={
                "board": board,
                "id": job_id,
                "employment": j.get("job_type"),
                "experience": j.get("experience_level"),
            },
        )
