"""ADP MyJobs career sites (myjobs.adp.com, a tenant is a site slug). Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

SITE = "https://myjobs.adp.com/public/staffing/v1/career-site/{slug}"
# "myadp_prefix" is a literal path segment on ADP's host, not a placeholder.
LIST = "https://my.adp.com/myadp_prefix/mycareer/public/staffing/v1/job-requisitions"
PAGE_URL = "https://myjobs.adp.com/{slug}/cx/job/{id}"
PAGE_SIZE = 50
_URL = re.compile(r"myjobs\.adp\.com/([\w-]+)/cx/job/([\w-]+)", re.I)


class AdpMyJobs(Source):
    name = "adpmyjobs"
    kind = "ats"
    url_patterns = (
        re.compile(r"myjobs\.adp\.com/public/staffing/v1/career-site/([\w-]+)", re.I),
        re.compile(r"myjobs\.adp\.com/(?!public/)([\w-]+)/cx", re.I),
    )
    parallel = 2  # public JSON API; Http paces per host

    def __init__(self) -> None:
        self._sites: dict[str, dict[str, Any]] = {}

    async def _site(self, http: Http, slug: str) -> dict[str, Any]:
        """The career site's public record: its `orgoid` authorises the listing requests."""
        if slug not in self._sites:
            site = await http.get_json(SITE.format(slug=slug))
            if not site.get("orgoid"):
                raise ValueError(f"adpmyjobs: career site {slug} published no orgoid")
            self._sites[slug] = site
        return self._sites[slug]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slug = task.board.strip()
        site = await self._site(http, slug)
        headers = {"orgoid": site["orgoid"]}
        company = (site.get("clientName") or site.get("name") or slug).strip()

        async def fetch(skip: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(
                LIST, params={"$top": PAGE_SIZE, "$skip": skip}, headers=headers
            )
            return data.get("jobRequisitions") or [], data.get("count")

        async for items in paged(fetch, PAGE_SIZE, start_page):
            yield [self.stub(r, slug, company) for r in items if r.get("reqId")]

    @staticmethod
    def stub(r: dict[str, Any], slug: str, company: str) -> JobStub:
        url = PAGE_URL.format(slug=slug, id=r["reqId"])
        places = (loc.get("address") or {} for loc in r.get("requisitionLocations") or [])
        first = next(places, {})
        parts = (
            first.get("cityName"),
            (first.get("countrySubdivisionLevel1") or {}).get("longName"),
            (first.get("country") or {}).get("longName"),
        )
        location = ", ".join(p.strip() for p in parts if p and p.strip())
        return JobStub(
            source="adpmyjobs",
            url=url,
            title=(r.get("jobTitle") or "").strip(),
            company=company,
            location=location,
            description=html_to_text(r.get("jobDescription") or "", escaped=True),
            posted_at=from_iso(r.get("postingDate")),
            ats="adpmyjobs",
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": slug, "id": r["reqId"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        slug, req = m.groups()
        site = await self._site(http, slug)
        data = await http.get_json(f"{LIST}/{req}", headers={"orgoid": site["orgoid"]})
        found = data.get("jobRequisitions") or []  # same envelope as the list, one entry long
        if not found:
            return stub
        company = (site.get("clientName") or site.get("name") or slug).strip()
        return self.stub(found[0], slug, company)
