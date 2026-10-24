"""a16z speedrun talent network (speedrun-talent-network.com): the board is a company slug. Its
roles are the ones that apply on the network itself or through the company's own ATS. Logic
adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlsplit

from linkit_all.sources.ats._f13 import mode, name_from_slug
from linkit_all.sources.ats._f16 import when
from linkit_all.sources.ats._f17 import hydrate
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http

_HOST = "speedrun-talent-network.com"
_API = f"https://{_HOST}/api/v1"
_TAG = "source=linkit"  # the API asks every integration to name itself


class Speedrun(Source):
    name = "speedrun"
    kind = "ats"
    url_patterns = (re.compile(rf"{re.escape(_HOST)}/companies/([\w-]+)", re.I),)
    cdx_hosts = (f"{_HOST}/companies/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slug = quote(task.board, safe="")
        body = await http.get_json(f"{_API}/companies/{slug}?{_TAG}")
        company = body.get("company") or {}
        name = company.get("name") or name_from_slug(task.board)
        ids = [str(j["id"]) for j in company.get("jobs") or [] if j.get("id")]

        async def build(job_id: str) -> JobStub | None:
            resp = await http.get(f"{_API}/jobs/{quote(job_id, safe='')}?{_TAG}")
            if resp.status_code in (404, 410):
                return None
            resp.raise_for_status()
            return self._stub(resp.json().get("job") or {}, task.board, name, job_id)

        async for stubs in hydrate(ids, start_page, build, 20):
            yield stubs

    def _stub(self, job: dict[str, Any], board: str, company: str, job_id: str) -> JobStub | None:
        title = " ".join(str(job.get("title") or "").split())
        if job.get("status") == "closed" or not title:
            return None
        # Where one applies: the company's own ATS for a federated role, else the network page.
        url = ((job.get("apply") or {}).get("url") or job.get("url") or "").strip()
        if not url:
            return None
        location = str(job.get("location") or "").strip()
        text = [str(job.get(k) or "").strip() for k in ("comp_summary", "description_text")]
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=location,
            description="\n\n".join(t for t in text if t),
            posted_at=when(job.get("published_at")),
            # an external ATS URL is left to the apply stage's own detection
            ats=self.name if urlsplit(url).hostname == _HOST else None,
            apply_url=url,
            remote="remote"
            if job.get("remote")
            else mode(job.get("workplace_type")) or remote_from_text(location),
            extra={"board": board, "id": job_id},
        )
