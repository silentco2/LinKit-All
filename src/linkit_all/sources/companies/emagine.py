"""emagine's consultant portal (portal.emagine.org): a European freelance-contract marketplace. One
public API lists every assignment (POST, no description); `fetch_details` reads each one's body.
The portal never names the end client, so the employer is emagine itself. A single-company plugin,
not an ATS. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode

HOST = "portal-api.emagine.org"
PAGE = 500
SEARCH = "https://{host}/api/JobAds/Search"
DETAIL = "https://{host}/api/JobAds/details/{id}/EN"
JOB = "https://portal.emagine.org/jobs/{id}/{slug}"
_ID = re.compile(r"/jobs/(\d+)(?:[/?#]|$)")
# Every collection of the filter block is required: null (or a missing key) is a 400.
_FILTER_LISTS = (
    "textFilters",
    "workLocationTypes",
    "workLocations",
    "professionalRolesIds",
    "consultantSeniorities",
    "languageProficiencies",
    "industriesIds",
    "recordIdsToExclude",
)


class Emagine(Source):
    name = "emagine"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "emagine:assignments", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            body = {
                "skipCount": offset,
                "maxResultCount": PAGE,
                "sorting": "Id asc",  # stable under concurrent publishing, unlike recency
                "filter": {k: [] for k in _FILTER_LISTS},
                "supportedLanguageId": "EN",  # omitting it is a 500
            }
            data = await http.post_json(SEARCH.format(host=task.board), body)
            return data.get("items") or [], data.get("totalCount")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for ad in items if (s := self.stub(ad))]

    def stub(self, ad: dict[str, Any]) -> JobStub | None:
        title = " ".join((ad.get("title") or "").split())
        if not ad.get("id") or not title:
            return None
        where = ad.get("jobAdWorkLocation") or {}
        place = (where.get("city"), where.get("region"), where.get("country"))
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")  # decorative: routing is by id
        url = JOB.format(id=ad["id"], slug=slug)
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="emagine",
            location=", ".join(dict.fromkeys(p for p in place if p)),
            ats=self.name,
            apply_url=url,
            remote=mode(where.get("workLocationType")),
            extra={
                "id": str(ad["id"]),
                "employment": "part_time" if ad.get("isPartTime") else "contract",
                "area": (ad.get("area") or {}).get("name"),
            },
        )  # no date: startDate is when the consultant starts, not when the ad went up

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not (m := _ID.search(stub.url)):
            return stub
        data = await http.get_json(DETAIL.format(host=HOST, id=m[1]))
        return stub.model_copy(update={"description": strip_html(data.get("description") or "")})
