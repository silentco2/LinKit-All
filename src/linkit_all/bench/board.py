"""The fake job board (a small web app) and the source plugin that reads it.

The list page gives every other job without its description, so the enrich stage has real work:
it reads those from the job page's JSON-LD with the same parser the real sites use.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from linkit_all.bench.data import FakeJob
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub

HOST = "fakeboard.test"
BASE = f"http://{HOST}"
PER_PAGE = 100


def make_app(jobs: list[FakeJob], now: datetime) -> FastAPI:
    app = FastAPI()
    by_uid = {j.uid: j for j in jobs}

    def posted(j: FakeJob) -> str:
        return (now - timedelta(days=j.posted_days_ago)).isoformat()

    @app.get("/api/jobs")
    def listing(page: int = 0) -> dict[str, Any]:
        rows = jobs[page * PER_PAGE : (page + 1) * PER_PAGE]
        return {
            "jobs": [
                {
                    "id": j.uid,
                    "title": j.title,
                    "company": j.company,
                    "location": j.location,
                    "posted_at": posted(j),
                    "description": j.description if j.uid % 2 == 0 else "",
                }
                for j in rows
            ]
        }

    @app.get("/jobs/{uid}", response_class=HTMLResponse)
    def detail(uid: int) -> str:
        j = by_uid.get(uid)
        if j is None:
            raise HTTPException(404)
        posting = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": j.title,
            "description": f"<p>{j.description}</p>",
            "datePosted": posted(j),
            "hiringOrganization": {"@type": "Organization", "name": j.company},
            "jobLocation": {"@type": "Place", "address": j.location},
        }
        return (
            f"<html><head><title>{j.title}</title>"
            f'<script type="application/ld+json">{json.dumps(posting)}</script></head>'
            f"<body><h1>{j.title}</h1><p>{j.description}</p></body></html>"
        )

    return app


class FakeBoard(Source):
    name = "fakeboard"
    kind = "board"
    default_on = True

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, f"{self.name}:all")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        page = start_page
        while rows := (await http.get_json(f"{BASE}/api/jobs", params={"page": page}))["jobs"]:
            yield [
                JobStub(
                    source=self.name,
                    url=f"{BASE}/jobs/{r['id']}",
                    title=r["title"],
                    company=r["company"],
                    location=r["location"],
                    description=r["description"],
                    posted_at=from_iso(r["posted_at"]),
                    remote=remote_from_text(r["location"]),
                )
                for r in rows
            ]
            page += 1

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        resp = await http.get(stub.url)
        return to_stub(job_postings(resp.text)[0], self.name, stub.url, None)
