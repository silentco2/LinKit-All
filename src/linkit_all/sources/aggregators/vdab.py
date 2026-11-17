"""VDAB (vdab.be), Flanders' public employment service, through the search API its own job
pages call. That API wants the `vej-key-monitor` header the site's script sends; the value is
read from the site's current script bundle each run (not stored here) and read again once if
the API refuses it. One task per search query; postings from the last 30 days, 100 a page.
The list has no body: `fetch_details` reads the posting's own record.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, json_or_none, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date
from linkit_all.sources.tasks import limited, query_tasks

SEARCH = "https://www.vdab.be/rest/vindeenjob/v4/vacatureLight/zoek"
DETAIL = "https://www.vdab.be/rest/vindeenjob/v4/vacatures/{}"
JOB = "https://www.vdab.be/vindeenjob/vacatures/{}"
APP_PAGE = "https://www.vdab.be/vindeenjob/vacatures"
PAGE = 100
MAX_PAGES = 50
_BUNDLE = re.compile(r"https://www\.vdab\.be/webapps/vindeenjob/main-[\w-]+\.js")
_KEY = re.compile(
    r'vej-key-monitor","([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"', re.I
)
_CODES = (
    "diplomaCodes", "arbeidsduurCodes", "arbeidsregimeCodes", "contractTypeCodes",
    "jobdomeinCodes", "internationaalCodes", "beroepCodes", "ervaringCodes",
    "rijbewijsCodes", "attestCodes",
)  # fmt: skip


def search_body(query: str, page: int, days: int = 30) -> dict[str, Any]:
    """The search the site's own page posts, every filter left empty."""
    criteria: dict[str, Any] = {"trefwoord": query, **{k: [] for k in _CODES}}
    criteria |= {
        "taalCriteria": {"taalSelecties": []},
        "onlineSindsCode": str(days),
        "sorteerVeld": "STANDAARD",
    }
    return {"criteria": criteria, "pagina": page, "zoekmodus": "C2", "paginaGrootte": PAGE}


class Vdab(Source):
    name = "vdab"
    kind = "aggregator"

    def __init__(self) -> None:
        self._key: str | None = None

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def _site_key(self, http: Http) -> str:
        bundle = _BUNDLE.search((await get_page(http, APP_PAGE)).text)
        key = _KEY.search((await get_page(http, bundle[0])).text) if bundle else None
        if not key:
            raise ValueError("vdab: the site's script carries no search key (site changed?)")
        self._key = key[1]
        return self._key

    async def _post(self, http: Http, body: dict[str, Any]) -> Any:
        for attempt in range(2):
            key = self._key if self._key and attempt == 0 else await self._site_key(http)
            resp = await http.request("POST", SEARCH, json=body, headers={"vej-key-monitor": key})
            if resp.status_code != 403:
                resp.raise_for_status()
                return resp.json()
            self._key = None
        resp.raise_for_status()

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        days = max(1, min(task.posted_within_days, 30))
        for page in range(start_page, MAX_PAGES):
            data = await self._post(http, search_body(task.query, page, days))
            rows = data.get("resultaten") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("vdab: the response carries no resultaten array")
            yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            if len(rows) < PAGE:
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        jid = str((r.get("id") or {}).get("id") or "").strip()
        title = clean((r.get("vacaturefunctie") or {}).get("naam"))
        company = clean(r.get("vacatureBedrijfsnaam"))
        if not (jid and title and company):
            return None
        where = clean(r.get("tewerkstellingsLocatieRegioOfAdres"))
        url = JOB.format(quote(jid, safe=""))
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=where,
            posted_at=safe_date(r.get("eerstePublicatieDatum")),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(where),
            extra={"id": jid},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        jid = stub.url.rstrip("/").rsplit("/", 1)[-1]  # enrich hands a bare stub: url only
        key = self._key or await self._site_key(http)
        data = await json_or_none(
            http,
            DETAIL.format(jid),
            params={"preview": "false"},
            headers={"vej-key-monitor": key, "Accept": "application/json"},
        )
        about = (
            ((data or {}).get("functie") or {}).get("omschrijving")
            if isinstance(data, dict)
            else None
        )
        text = (
            (about.get("markdown") or about.get("plainText") or "")
            if isinstance(about, dict)
            else ""
        )
        body = strip_html(text) if "<" in text else str(text).strip()
        return stub.model_copy(update={"description": body}) if body else stub
