"""Career sites on the recruiting-solutions.org "Career Site Builder" (e.g. Bertelsmann's
createyourowncareer.com), read through the keyless search API behind them. Logic adapted from
freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import chunks
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://production.api.recruiting-solutions.org/search"
PAGE = 50
_MODES: dict[str, Remote] = {
    "telecommute1": "hybrid",
    "telecommute2": "remote",
    "telecommute3": "onsite",
}
_LOCALE_RANK = {"en_GB": 3, "en_US": 2}


def split_id(job_id: str) -> tuple[str, str]:
    """ "274342-en_GB" -> ("274342", "en_GB"): the index keeps one record per UI locale."""
    base, _, locale = job_id.partition("-")
    return base, locale


class RecruitingSolutions(Source):
    """The board is the tenant key sent as the `customerId` header (e.g. `riv-prod`). One tenant
    can host several operating companies, so the company comes from each record. The tenants'
    own hosts differ, so there is no URL pattern: list one as `recruitingsolutions:riv-prod`."""

    name = "recruitingsolutions"
    kind = "ats"
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        best: dict[str, dict[str, Any]] = {}  # base id -> the preferred locale's record
        skip = 0
        while True:
            body = {"count": True, "facets": [], "filter": "", "search": "*", "skip": skip}
            data = await http.post_json(API, body, headers={"customerId": task.board})
            records = data.get("value") or []
            for r in records:
                base, locale = split_id(r.get("jobId") or "")
                if not base or not r.get("isActive"):
                    continue
                cur = best.get(base)
                rank = _LOCALE_RANK.get
                if cur is None or rank(locale, 1) > rank(split_id(cur["jobId"])[1], 1):
                    best[base] = r
            skip += PAGE
            if not records or skip >= (data.get("@odata.count") or 0):
                break
        # Locales of one posting can sit on different pages, so only now are the records final.
        stubs = [self.stub(b, r, task.board) for b, r in best.items() if r.get("link")]
        for chunk in chunks(stubs, start_page, 100):
            yield list(chunk)

    @staticmethod
    def stub(base: str, r: dict[str, Any], board: str) -> JobStub:
        url = r["link"].partition("?")[0]  # drop the locale query: one canonical URL per posting
        city = (r.get("location") or {}).get("city")
        return JobStub(
            source="recruitingsolutions",
            url=url,
            title=(r.get("title") or "").strip(),
            company=r.get("company") or "Unknown",
            location=", ".join(p for p in (city, r.get("country")) if p),
            description=html_to_text(r.get("description") or ""),
            posted_at=from_iso(r.get("datePosted")),
            ats="recruitingsolutions",
            apply_url=url,
            remote=_MODES.get(r.get("teleComuteId") or ""),
            extra={"board": board, "id": base},
        )
