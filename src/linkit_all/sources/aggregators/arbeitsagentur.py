"""Bundesagentur fuer Arbeit (arbeitsagentur.de), Germany's federal employment agency, through
its open jobsuche API and the public X-API-Key the agency publishes for it.
Logic adapted from freehire (MIT)."""

import base64
from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import query_tasks

SEARCH = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
DETAIL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/"
PAGE_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/"
HEADERS = {"X-API-Key": "jobboerse-jobsuche"}  # published by the agency for its open API
PAGE = 100
MAX_DAYS = 100  # the API's `veroeffentlichtseit` ceiling


def _pretty(part: str | None) -> str:
    """ "NORDRHEIN_WESTFALEN" -> "Nordrhein Westfalen"; the API's literal "null" -> ""."""
    part = (part or "").strip()
    if part == "null":
        return ""
    return part.replace("_", " ").title() if part.isupper() else part


class Arbeitsagentur(Source):
    name = "arbeitsagentur"
    kind = "aggregator"
    parallel = 2  # public JSON API; Http paces per host

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, ceil(task.limit / PAGE) + 1):
            params: dict[str, Any] = {
                "was": task.query,
                "size": PAGE,
                "page": page,
                "veroeffentlichtseit": min(task.posted_within_days, MAX_DAYS),
            }
            if task.location:
                params["wo"] = task.location
            data = await http.get_json(SEARCH, params=params, headers=HEADERS)
            rows = data.get("ergebnisliste") or []
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            if len(rows) < PAGE or page * PAGE >= data.get("maxErgebnisse", 0):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        ref = p.get("referenznummer")
        if not ref or not p.get("stellenangebotsTitel"):
            return None
        url = PAGE_URL + ref
        remote: Remote | None = None
        if p.get("homeofficemoeglich"):
            remote = "remote" if "VOLL" in (p.get("homeofficetyp") or "") else "hybrid"
        return JobStub(
            source=self.name,
            url=url,
            title=p["stellenangebotsTitel"].strip(),
            company=(p.get("firma") or "").strip() or "Unknown",
            location=self._location(p.get("stellenlokationen") or []),
            posted_at=from_iso(p.get("datumErsteVeroeffentlichung")),
            apply_url=(p.get("externeURL") or "").strip() or url,
            remote=remote,
            extra={"id": ref},
        )

    @staticmethod
    def _location(places: list[dict[str, Any]]) -> str:
        addr = (places[0].get("adresse") or {}) if places else {}
        parts = (_pretty(addr.get(k)) for k in ("ort", "region", "land"))
        return ", ".join(p for p in parts if p)

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        ref = stub.url.rsplit("/", 1)[-1]
        resp = await http.get(DETAIL + base64.b64encode(ref.encode()).decode(), headers=HEADERS)
        if resp.status_code == 404:  # filled since the listing
            return stub
        resp.raise_for_status()
        text = (resp.json().get("stellenangebotsBeschreibung") or "").replace("\r", "").strip()
        return stub.model_copy(update={"description": text})
