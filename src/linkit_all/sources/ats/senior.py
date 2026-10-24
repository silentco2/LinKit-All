"""Senior "Portal de Talentos" (careersmanager candidate bridge API on platform.senior.com.br),
Brazil. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

BASE = (
    "https://platform.senior.com.br/t/senior.com.br/bridge/1.0/anonymous/rest/hcm/"
    "careersmanagercandidate"
)
JOB_URL = "https://{board}.portaldetalentos.senior.com.br/vacancy/{id}"
_URL = re.compile(r"//([\w-]+)\.portaldetalentos\.senior\.com\.br/vacancy/([\w-]+)", re.I)
PAGE = 50
# Several models may be listed; the most remote one wins.
_MODELS: tuple[tuple[str, Remote], ...] = (
    ("REMOTE", "remote"),
    ("HYBRID", "hybrid"),
    ("IN_PERSON", "onsite"),
)


def work_mode(models: list[str] | None) -> Remote | None:
    have = {str(m).strip().upper() for m in models or []}
    return next((r for key, r in _MODELS if key in have), None)


class Senior(Source):
    """The board is the tenant subdomain (`intelbras.portaldetalentos.senior.com.br`). The API
    is POST-only JSON: subdomain -> profile id -> paged vacancy search -> detail per vacancy."""

    name = "senior"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.portaldetalentos\.senior\.com\.br", re.I),)
    cdx_hosts = ("*.portaldetalentos.senior.com.br/*",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        res = await http.post_json(
            f"{BASE}/actions/getProfileIdBySubdomain", {"subdomain": task.board}
        )
        profile = res.get("profileId")
        if not profile:
            raise ValueError(f"senior: subdomain {task.board!r} has no profile id")
        company = name_from_slug(task.board)
        page = start_page
        while True:
            body = {
                "page": page,
                "size": PAGE,
                "filter": "",
                "match": {"companies": [{"id": profile}], "localizations": []},
            }
            data = await http.post_json(f"{BASE}/queries/searchVacancies", body)
            yield [
                self.stub(c["vacancy"], task.board, company)
                for c in data.get("contents") or []
                if (c.get("vacancy") or {}).get("id")
            ]
            page += 1
            if page >= (data.get("totalPages") or 0):
                return

    @staticmethod
    def stub(v: dict[str, Any], board: str, company: str) -> JobStub:
        loc = v.get("localization") or {}
        where = ", ".join(
            p for p in (loc.get("city"), loc.get("province"), loc.get("country")) if p
        )
        url = JOB_URL.format(board=board, id=v["id"])
        start = (v.get("publication") or {}).get("startDate")
        try:
            posted = from_iso(start)
        except ValueError:
            posted = None
        return JobStub(
            source="senior",
            url=url,
            title=(v.get("title") or "").strip(),
            company=company,
            location=where,
            posted_at=posted,
            ats="senior",
            apply_url=url,
            remote=work_mode(v.get("jobModel")),
            extra={"board": board, "id": v["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        data = await http.post_json(f"{BASE}/queries/findVacancyById", {"id": m.group(2)})
        about = (data.get("vacancy") or {}).get("about") or {}
        return stub.model_copy(update={"description": html_to_text(about.get("description") or "")})
