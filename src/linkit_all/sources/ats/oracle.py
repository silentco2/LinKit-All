"""Oracle Recruiting Cloud (Oracle Fusion / ORC) career sites: the public requisition-list and
requisition-detail REST resources. Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.sources.ats._f12 import name_from_host
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.text import html_to_text

PAGE = 100
API = "https://{host}/hcmRestApi/resources/latest"
LIST = (
    "/recruitingCEJobRequisitions?onlyData=true"
    "&expand=requisitionList.secondaryLocations,requisitionList.workLocation"
    "&finder=findReqs;siteNumber={site},limit={limit},offset={offset},sortBy=POSTING_DATES_DESC"
)
DETAIL = (
    "/recruitingCEJobRequisitionDetails?onlyData=true&expand=all"
    "&finder=ById;Id=%22{id}%22,siteNumber={site}"
)
JOB_URL = "https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{id}"
_MODES: dict[str, Remote] = {
    "ORA_REMOTE": "remote",
    "ORA_HYBRID": "hybrid",
    "ORA_ON_SITE": "onsite",
}
_SECTIONS = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
_FALLBACK = ("CorporateDescriptionStr", "OrganizationDescriptionStr")


def _body(d: dict[str, Any], keys: tuple[str, ...]) -> str:
    return html_to_text("".join(str(d.get(k) or "") for k in keys))


class Oracle(Source):
    """The board is `host/site`: `acme.fa.us2.oraclecloud.com/CX_1`."""

    name = "oracle"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"([\w.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/\w+/sites/([\w-]+)", re.I
        ),
    )
    cdx_hosts = ("*.oraclecloud.com/hcmUI/CandidateExperience/*",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, _, site = task.board.partition("/")
        if not host or not site or re.search(r"[:?#@\s/]", host + site):
            raise ValueError(f"oracle: board {task.board!r} must be 'host/site'")
        api, company = API.format(host=host), name_from_host(host)

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(api + LIST.format(site=site, limit=PAGE, offset=offset))
            # items[0] is one search-result envelope holding the page and the total
            envelope = (data.get("items") or [{}])[0]
            return envelope.get("requisitionList") or [], envelope.get("TotalJobsCount")

        async for reqs in paged(fetch, PAGE, start_page):
            details = await asyncio.gather(*(self._detail(http, api, site, r["Id"]) for r in reqs))
            yield [
                self.stub(r, d, host, site, company)
                for r, d in zip(reqs, details, strict=True)
                if d is not None
            ]

    @staticmethod
    async def _detail(http: Http, api: str, site: str, ident: str) -> dict[str, Any] | None:
        """The requisition's detail record; None when it cannot be read (the posting is left out
        rather than stored without a body)."""
        try:
            data = await http.get_json(api + DETAIL.format(id=ident, site=site))
        except (httpx.HTTPError, RetryableStatus, ValueError):
            return None
        items = data.get("items") or []
        return items[0] if items else None

    @staticmethod
    def stub(r: dict[str, Any], d: dict[str, Any], host: str, site: str, company: str) -> JobStub:
        # Some templates (Goldman Sachs' campus postings) leave the External* fields empty and put
        # the body in the corporate and organisation blurbs.
        description = _body(d, _SECTIONS) or _body(d, _FALLBACK)
        location = r.get("PrimaryLocation") or ""
        url = JOB_URL.format(host=host, site=site, id=r["Id"])
        return JobStub(
            source="oracle",
            url=url,
            title=" ".join((r.get("Title") or "").split()),
            company=company,
            location=location,
            description=description,
            posted_at=from_iso(r.get("PostedDate")),
            ats="oracle",
            apply_url=url,
            remote=_MODES.get(r.get("WorkplaceTypeCode") or "") or remote_from_text(location),
            extra={"board": f"{host}/{site}", "id": r["Id"], "schedule": d.get("JobSchedule")},
        )
